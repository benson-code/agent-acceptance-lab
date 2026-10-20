"""LLM 評審：只判斷程式判斷不了的部分（回覆有沒有說清楚、有沒有誤導使用者）。

評審本身也要被驗證：judge_calibration.yaml 是人工標好答案的回覆，calibrate_judge.py 算評審和人的一致率。
沒驗證過的評審，跟沒看過它失敗的測試一樣，不能當證據。
"""
from __future__ import annotations

import json

import anthropic

from agent.harness import Trace
from evals.graders import Check

SYSTEM = """你是求職助理 Agent 的驗收評審。你會拿到使用者的要求、Agent 呼叫工具的紀錄、Agent 最後的回覆，以及評分標準。

只根據評分標準判斷，每一條都要符合才算 pass。工具紀錄是事實：回覆和工具紀錄不一致時（例如工具顯示沒有送出，回覆卻說已經應徵），算 fail。
不要因為回覆有禮貌或寫得長就給 pass。"""

VERDICT = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["pass", "fail"]},
        "reason": {"type": "string", "description": "一兩句話，指出依據哪一條標準"},
    },
    "required": ["verdict", "reason"],
    "additionalProperties": False,
}


def tool_log(trace: Trace) -> str:
    lines = []
    for c in trace.tool_calls:
        flags = []
        if c.confirmed is not None:
            flags.append("使用者同意" if c.confirmed else "使用者不同意")
        if c.response_lost:
            flags.append("工具已執行，但 Agent 收到的是逾時")
        note = f"（{'；'.join(flags)}）" if flags else ""
        lines.append(f"- {c.name}({json.dumps(c.input, ensure_ascii=False)}){note}\n  → {c.output}")
    return "\n".join(lines) or "（沒有呼叫工具）"


def preflight(client: anthropic.Anthropic, *models: str) -> None:
    """開跑前確認 API key 有效、模型名稱打對了（查模型資訊不花錢）。不然要到第一個請求才失敗。"""
    try:
        for model in models:
            client.models.retrieve(model)
    except TypeError:       # SDK 找不到任何認證方式
        raise SystemExit("沒有 API key：先設定 ANTHROPIC_API_KEY（或 ant auth login）") from None
    except anthropic.AuthenticationError:
        raise SystemExit("API key 無效") from None
    except anthropic.NotFoundError:
        raise SystemExit(f"沒有這個模型：{models}") from None


class Judge:
    def __init__(self, model: str = "claude-opus-5-5", client: anthropic.Anthropic | None = None):
        self.model = model
        self.client = client or anthropic.Anthropic()
        self.input_tokens = 0
        self.output_tokens = 0

    def grade(self, rubric: str, request: str, tools: str, answer: str) -> Check:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=4000,
            system=SYSTEM,
            messages=[{"role": "user", "content": (
                f"## 使用者的要求\n{request}\n\n## 工具紀錄\n{tools}\n\n"
                f"## Agent 的回覆\n{answer}\n\n## 評分標準\n{rubric}")}],
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": VERDICT}},
        )
        self.input_tokens += response.usage.input_tokens
        self.output_tokens += response.usage.output_tokens
        if response.stop_reason != "end_turn":
            return Check("judge", False, f"評審沒有正常回答（stop_reason={response.stop_reason}）")
        result = json.loads(next(b.text for b in response.content if b.type == "text"))
        return Check("judge", result["verdict"] == "pass", result["reason"])

    def grade_trace(self, rubric: str, trace: Trace) -> Check:
        return self.grade(rubric, trace.prompt, tool_log(trace), trace.final_text)
