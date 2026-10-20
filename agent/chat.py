"""在終端機和 Agent 對話（真模型，需要 API key）。每則訊息各自獨立，Agent 不記得上一則。

    .venv/bin/python -m agent.chat
    AGENT_MODEL=claude-haiku-5-5 .venv/bin/python -m agent.chat

應徵前會問你 y/N；每一則回覆前會列出 Agent 呼叫了哪些工具。
"""
from __future__ import annotations

import json
import os

from agent.harness import Agent
from agent.models import ClaudeModel
from jobboard.board import JobBoard


def confirm(job: dict) -> bool:
    answer = input(f"\n  確定要應徵 {job['job_id']} {job['title']}（{job['company']}）嗎？[y/N] ")
    return answer.strip().lower() == "y"


def main() -> None:
    model = ClaudeModel(os.environ.get("AGENT_MODEL", "claude-opus-5-5"), os.environ.get("AGENT_EFFORT", "medium"))
    agent = Agent(model, JobBoard(), confirm=confirm)
    print(f"求職助理（{model.name}）。空白一行結束。")
    while prompt := input("\n你：").strip():
        trace = agent.run(prompt)
        for c in trace.tool_calls:
            print(f"  · {c.name}({json.dumps(c.input, ensure_ascii=False)}){'  ← 錯誤' if c.is_error else ''}")
        print(f"\n助理：{trace.final_text}")
        print(f"  （{trace.turns} 回合，{trace.elapsed_s:.1f} 秒，tokens 輸入 {trace.input_tokens:,} / 輸出 {trace.output_tokens:,}）")


if __name__ == "__main__":
    main()
