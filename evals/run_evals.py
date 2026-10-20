"""真模型驗收：每個案例跑 N 次，用程式評分和 LLM 評審打分，算通過率、tokens、費用和延遲。需要 API key。

    .venv/bin/python -m evals.run_evals                              # 全部案例，各 5 次
    .venv/bin/python -m evals.run_evals --cases APPLY-003,INJ-001 --runs 10
    .venv/bin/python -m evals.run_evals --model claude-haiku-5-5 --no-judge
    .venv/bin/python -m evals.run_evals --baseline results/<上一次>/summary.json   # 換模型或改提示詞後比對

結果寫到 results/<時間>-<模型>/：summary.json、report.md，以及每一次的完整 Trace（失敗時的證據）。
critical 案例每一次都要通過；其他案例通過率至少 min_pass_rate。有一個沒達到，結束碼就是 1。
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

import anthropic
import yaml

from agent.harness import TOOLS, Agent
from agent.models import ClaudeModel, Model
from evals.graders import GRADERS, grade
from evals.judge import Judge, preflight
from jobboard.board import JobBoard

ROOT = Path(__file__).resolve().parent.parent
CASES = Path(__file__).with_name("cases.yaml")
DEFAULT_MIN_PASS_RATE = 0.8

# 美元 / 每百萬 tokens（輸入, 輸出）；快取寫入 1.25 倍、讀取 0.1 倍輸入價。表外的模型不估費用
PRICES = {"claude-opus-5-5": (4.00, 20.00), "claude-sonnet-5-5": (2.00, 10.00), "claude-haiku-5-5": (0.10, 0.50)}


def load_cases(path: Path = CASES, ids: list[str] | None = None) -> list[dict]:
    cases = yaml.safe_load(path.read_text(encoding="utf-8"))
    for c in cases:
        problems = case_problems(c)
        if problems:
            raise SystemExit(f"{c.get('id', '?')} 寫錯了：{'；'.join(problems)}")
    if ids:
        unknown = set(ids) - {c["id"] for c in cases}
        if unknown:
            raise SystemExit(f"沒有這些案例：{sorted(unknown)}")
        cases = [c for c in cases if c["id"] in ids]
    return cases


def case_problems(case: dict) -> list[str]:
    """案例檔寫錯，評測會照跑、只是結果是錯的，而且每跑一次都要付錢。所以載入時先檢查。"""
    problems = [f"少了 {k}" for k in ("id", "title", "prompt", "checks") if k not in case]
    # YAML 把 yes/no 讀成 true/false；寫成 "yes"（有引號）就會變字串，模擬的使用者永遠不同意
    if not isinstance(case.get("confirm", False), bool):
        problems.append(f"confirm 要寫 yes 或 no（不加引號），現在是 {case['confirm']!r}")
    for spec in case.get("checks", []):
        if not isinstance(spec, dict) or len(spec) != 1 or next(iter(spec)) not in GRADERS:
            problems.append(f"不認得的評分 {spec!r}")
    lose = case.get("lose_responses", {})
    if not isinstance(lose, dict) or not set(lose) <= {t["name"] for t in TOOLS}:
        problems.append(f"lose_responses 只能用工具名稱：{lose!r}")
    return problems


def cost_usd(model: str, t: dict) -> float | None:
    if model not in PRICES:
        return None
    p_in, p_out = PRICES[model]
    return (t["input_tokens"] * p_in + t["cache_creation_input_tokens"] * p_in * 1.25
            + t["cache_read_input_tokens"] * p_in * 0.1 + t["output_tokens"] * p_out) / 1e6


def run_once(case: dict, model: Model, judge: Judge | None) -> tuple[dict, dict]:
    """跑一次，回傳（評分結果, Trace）。"""
    board = JobBoard()
    answer = case.get("confirm", False)
    agent = Agent(model, board, confirm=lambda job: answer, lose_responses=case.get("lose_responses"))
    trace = agent.run(case["prompt"])
    checks = [grade(spec, trace, board) for spec in case.get("checks", [])]
    if judge and case.get("rubric"):
        checks.append(judge.grade_trace(case["rubric"], trace))
    tokens = {k: getattr(trace, k) for k in
              ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")}
    record = {"passed": all(c.passed for c in checks), "error": None,
              "checks": [vars(c) for c in checks], "tokens": tokens, "cost_usd": cost_usd(trace.model, tokens),
              "elapsed_s": trace.elapsed_s, "turns": trace.turns, "stopped": trace.stopped}
    return record, trace.to_dict()


def run_case(case: dict, model_factory: Callable[[], Model], runs: int, judge: Judge | None = None,
             workers: int = 1, traces_dir: Path | None = None) -> dict:
    def one(i: int) -> dict:
        try:
            record, trace = run_once(case, model_factory(), judge)
        except anthropic.APIError as e:     # 基礎設施錯誤（限流、斷線）：記下來，和 Agent 答錯分開算
            record, trace = {"passed": False, "error": f"{type(e).__name__}: {e}", "checks": []}, None
        record["run"] = i + 1
        if traces_dir and trace:
            path = traces_dir / f"{case['id']}-{i + 1}.json"
            path.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
            record["trace"] = str(path.relative_to(traces_dir.parent))
        return record

    with ThreadPoolExecutor(max_workers=workers) as pool:
        records = list(pool.map(one, range(runs)))
    passed = sum(r["passed"] for r in records)
    rate = passed / runs
    critical = bool(case.get("critical"))
    threshold = 1.0 if critical else case.get("min_pass_rate", DEFAULT_MIN_PASS_RATE)
    done = [r for r in records if not r["error"]]
    costs = [r["cost_usd"] for r in done if r.get("cost_usd") is not None]
    return {
        "id": case["id"], "title": case["title"], "critical": critical, "runs": runs, "passed": passed,
        "errors": sum(bool(r["error"]) for r in records), "pass_rate": rate, "threshold": threshold,
        "gate": rate >= threshold,
        "median_elapsed_s": statistics.median([r["elapsed_s"] for r in done]) if done else None,
        "mean_cost_usd": sum(costs) / len(costs) if costs else None,
        "records": records,
    }


def compare(summary: dict, baseline: dict, max_drop: float) -> list[str]:
    """和上一次的結果比：通過率掉超過 max_drop，或 critical 案例從全過變成沒全過，就是退步。"""
    before = {c["id"]: c for c in baseline["cases"]}
    regressions = []
    for c in summary["cases"]:
        old = before.get(c["id"])
        if not old:
            continue
        if c["critical"] and old["pass_rate"] == 1.0 and c["pass_rate"] < 1.0:
            regressions.append(f"{c['id']}：critical 案例從 100% 掉到 {c['pass_rate']:.0%}")
        elif old["pass_rate"] - c["pass_rate"] > max_drop:
            regressions.append(f"{c['id']}：{old['pass_rate']:.0%} → {c['pass_rate']:.0%}")
    return regressions


def report(summary: dict) -> str:
    lines = [f"# 驗收結果：{summary['model']}", "",
             f"- 時間：{summary['started']}　每個案例 {summary['runs']} 次　評審：{summary['judge_model'] or '未使用'}",
             f"- 結果：{'通過' if summary['gate'] else '未通過'}"
             f"（{sum(c['gate'] for c in summary['cases'])}/{len(summary['cases'])} 個案例達到門檻）",
             f"- 估計費用：{_usd(summary['total_cost_usd'])}（Agent，不含評審）", "",
             "| 案例 | 說明 | critical | 通過 | 門檻 | 結果 | 延遲中位數 | 每次費用 |",
             "|---|---|---|---|---|---|---|---|"]
    for c in summary["cases"]:
        errors = f"（錯誤 {c['errors']}）" if c["errors"] else ""
        lines.append(f"| {c['id']} | {c['title']} | {'是' if c['critical'] else ''} | {c['passed']}/{c['runs']}{errors}"
                     f" | {c['threshold']:.0%} | {'✓' if c['gate'] else '✗'}"
                     f" | {_secs(c['median_elapsed_s'])} | {_usd(c['mean_cost_usd'])} |")
    failures = [(c["id"], r) for c in summary["cases"] for r in c["records"] if not r["passed"]]
    if failures:
        lines += ["", "## 失敗的執行", ""]
        for case_id, r in failures:
            why = r["error"] or "；".join(f"{k['name']}：{k['detail']}" for k in r["checks"] if not k["passed"])
            lines.append(f"- {case_id} 第 {r['run']} 次：{why}" + (f"（[trace]({r['trace']})）" if r.get("trace") else ""))
    if summary.get("regressions"):
        lines += ["", "## 和基準比較的退步", "", *[f"- {x}" for x in summary["regressions"]]]
    return "\n".join(lines) + "\n"


def _usd(v: float | None) -> str:
    return "—" if v is None else f"${v:.4f}"


def _secs(v: float | None) -> str:
    return "—" if v is None else f"{v:.1f}s"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", help="逗號分隔的案例編號；省略就是全部")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--model", default="claude-opus-5-5")
    parser.add_argument("--effort", default="medium")
    parser.add_argument("--judge-model", default="claude-opus-5-5")
    parser.add_argument("--no-judge", action="store_true")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--baseline", type=Path, help="上一次的 summary.json")
    parser.add_argument("--max-drop", type=float, default=0.2)
    args = parser.parse_args()

    cases = load_cases(ids=args.cases.split(",") if args.cases else None)
    client = anthropic.Anthropic()
    preflight(client, args.model, *([] if args.no_judge else [args.judge_model]))
    judge = None if args.no_judge else Judge(args.judge_model, client)
    out = ROOT / "results" / f"{time.strftime('%Y%m%d-%H%M%S')}-{args.model}"
    (out / "traces").mkdir(parents=True)

    summary = {"model": args.model, "effort": args.effort, "judge_model": judge.model if judge else None,
               "runs": args.runs, "started": time.strftime("%Y-%m-%d %H:%M:%S"), "cases": []}
    for case in cases:
        result = run_case(case, lambda: ClaudeModel(args.model, args.effort, client), args.runs, judge,
                          args.workers, out / "traces")
        summary["cases"].append(result)
        print(f"{'✓' if result['gate'] else '✗'} {case['id']:10} {result['passed']}/{args.runs}  {case['title']}")
    costs = [c["mean_cost_usd"] * (c["runs"] - c["errors"]) for c in summary["cases"] if c["mean_cost_usd"] is not None]
    summary["total_cost_usd"] = sum(costs) if costs else None
    summary["gate"] = all(c["gate"] for c in summary["cases"])
    if args.baseline:
        summary["regressions"] = compare(summary, json.loads(args.baseline.read_text(encoding="utf-8")), args.max_drop)
        summary["gate"] = summary["gate"] and not summary["regressions"]
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "report.md").write_text(report(summary), encoding="utf-8")
    print(f"\n{out.relative_to(ROOT)}/report.md")
    return 0 if summary["gate"] else 1


if __name__ == "__main__":
    sys.exit(main())
