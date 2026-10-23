"""在終端機和 Agent 對話（真模型，需要 API key）。每則訊息各自獨立，Agent 不記得上一則。

    .venv/bin/python -m agent.chat                  # 求職者王小明
    .venv/bin/python -m agent.chat --as C-01        # 企業：晨光科技（C-02 是青田數位）
    AGENT_MODEL=claude-haiku-5-5 .venv/bin/python -m agent.chat

應徵、改應徵狀態前會問你 y/N；每一則回覆前會列出 Agent 呼叫了哪些工具。
"""
from __future__ import annotations

import argparse
import json
import os

from agent.harness import Agent
from agent.models import ClaudeModel
from jobboard.board import JobBoard, Session


def confirm(action: dict) -> bool:
    if action["action"] == "apply_job":
        question = f"確定要應徵 {action['job_id']} {action['title']}（{action['company']}）嗎？"
    else:
        question = (f"確定要把 {action['name']} 應徵 {action['job_id']} 的狀態"
                    f"從 {action['from']} 改成 {action['to']} 嗎？")
    return input(f"\n  {question}[y/N] ").strip().lower() == "y"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--as", dest="who", default="U-001", help="U-001（求職者）、C-01 或 C-02（企業）")
    args = parser.parse_args()
    board = JobBoard()
    if args.who in board.companies:
        session, name = Session("employer", args.who), board.companies[args.who]["name"]
    elif args.who in board.seekers:
        session, name = Session("seeker", args.who), board.seekers[args.who]["name"]
    else:
        raise SystemExit(f"沒有 {args.who}：可以用 {sorted(board.seekers)} 或 {sorted(board.companies)}")

    model = ClaudeModel(os.environ.get("AGENT_MODEL", "claude-opus-5-5"), os.environ.get("AGENT_EFFORT", "medium"))
    agent = Agent(model, board, confirm=confirm, session=session)
    print(f"{'招募' if session.role == 'employer' else '求職'}助理（{model.name}），登入身分：{name}。空白一行結束。")
    while prompt := input("\n你：").strip():
        trace = agent.run(prompt)
        for c in trace.tool_calls:
            note = f"  ← 擋下（{c.blocked}）" if c.blocked else "  ← 錯誤" if c.is_error else ""
            print(f"  · {c.name}({json.dumps(c.input, ensure_ascii=False)}){note}")
        print(f"\n助理：{trace.final_text}")
        print(f"  （{trace.turns} 回合，{trace.elapsed_s:.1f} 秒，tokens 輸入 {trace.input_tokens:,} / 輸出 {trace.output_tokens:,}）")


if __name__ == "__main__":
    main()
