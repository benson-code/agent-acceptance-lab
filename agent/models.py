"""Agent 背後的模型：真的 Claude，或照劇本回應的假模型。

兩者回傳的都是 anthropic SDK 的 Message，所以 harness 不知道、也不需要知道自己接的是哪一個。
"""
from __future__ import annotations

import itertools
from typing import Callable, Protocol

import anthropic
from anthropic.types import Message


class Model(Protocol):
    name: str

    def respond(self, system: str, tools: list[dict], messages: list[dict]) -> Message: ...


class ClaudeModel:
    """真的 Claude（Messages API）。需要 ANTHROPIC_API_KEY 或 `ant auth login`。"""

    def __init__(self, name: str = "claude-opus-5-5", effort: str = "medium",
                 client: anthropic.Anthropic | None = None):
        self.name = name
        self.effort = effort
        self.client = client or anthropic.Anthropic()

    def respond(self, system: str, tools: list[dict], messages: list[dict]) -> Message:
        return self.client.messages.create(
            model=self.name,
            max_tokens=16000,
            system=system,
            tools=tools,
            messages=messages,
            output_config={"effort": self.effort},
            cache_control={"type": "ephemeral"},   # system 和工具每回合都一樣，快取起來
        )


class ScriptExhausted(AssertionError):
    """劇本已經用完，Agent 卻還在呼叫模型。"""


Turn = list | dict | Callable[[list[dict]], list | dict]


class ScriptedModel:
    """照劇本回應的假模型：不用 API key、每次結果都一樣，用來測 harness 和工具。

    劇本是一串回合，每個回合是一串區塊：字串是文字，(工具名稱, 參數) 是一次工具呼叫。
    回合也可以是 {"content": [...], "stop_reason": "refusal"}，或一個收到 messages、回傳回合的函式。
    """

    name = "scripted"

    def __init__(self, turns: list[Turn]):
        self.turns = iter(turns)
        self.requests: list[dict] = []
        self._ids = itertools.count(1)

    @classmethod
    def forever(cls, turn: Turn, limit: int = 30) -> "ScriptedModel":
        """一直重複同一個回合（測回合上限用）；超過 limit 次就丟 ScriptExhausted，避免測試卡住。"""
        return cls([turn] * limit)

    def respond(self, system: str, tools: list[dict], messages: list[dict]) -> Message:
        self.requests.append({"system": system, "tools": tools, "messages": list(messages)})
        try:
            turn = next(self.turns)
        except StopIteration:
            raise ScriptExhausted(f"劇本只有 {len(self.requests) - 1} 個回合，Agent 呼叫了第 {len(self.requests)} 次") from None
        if callable(turn):
            turn = turn(messages)
        stop_reason = None
        if isinstance(turn, dict):
            stop_reason, turn = turn["stop_reason"], turn["content"]
        content = []
        for block in turn:
            if isinstance(block, str):
                content.append({"type": "text", "text": block})
            else:
                name, args = block
                content.append({"type": "tool_use", "id": f"toolu_{next(self._ids):03d}", "name": name, "input": args})
        if stop_reason is None:
            stop_reason = "tool_use" if any(b["type"] == "tool_use" for b in content) else "end_turn"
        return Message.model_validate({
            "id": f"msg_scripted_{len(self.requests)}", "type": "message", "role": "assistant",
            "model": self.name, "content": content, "stop_reason": stop_reason, "stop_sequence": None,
            "usage": {"input_tokens": 0, "output_tokens": 0},
        })
