"""驗證 LLM 評審：拿人工標好答案的回覆給評審判斷，算一致率。需要 API key。

    .venv/bin/python -m evals.calibrate_judge                       # 預設評審模型
    .venv/bin/python -m evals.calibrate_judge --judge-model claude-sonnet-5-5 --min-agreement 1.0

一致率低於 --min-agreement（預設 0.875，8 筆最多錯 1 筆）就失敗：這個評審的判斷不能拿來當驗收結果。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import anthropic
import yaml

from evals.judge import Judge, preflight

CALIBRATION = Path(__file__).with_name("judge_calibration.yaml")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--judge-model", default="claude-opus-5-5")
    parser.add_argument("--min-agreement", type=float, default=0.875)
    args = parser.parse_args()

    client = anthropic.Anthropic()
    preflight(client, args.judge_model)
    judge = Judge(args.judge_model, client)
    items = yaml.safe_load(CALIBRATION.read_text(encoding="utf-8"))
    agree = 0
    for item in items:
        check = judge.grade(item["rubric"], item["request"], item["tools"], item["answer"])
        verdict = "pass" if check.passed else "fail"
        same = verdict == item["label"]
        agree += same
        print(f"{'✓' if same else '✗'} {item['id']}  人工 {item['label']:4}  評審 {verdict:4}  {check.detail}")
    rate = agree / len(items)
    print(f"\n一致率 {agree}/{len(items)} = {rate:.0%}（門檻 {args.min_agreement:.0%}）"
          f"  tokens：輸入 {judge.input_tokens:,}，輸出 {judge.output_tokens:,}")
    return 0 if rate >= args.min_agreement else 1


if __name__ == "__main__":
    sys.exit(main())
