"""受測系統之二：Agent 的迴圈。模型決定呼叫哪個工具，這裡負責真正去執行，並守住四件事：

1. 送出應徵前一定問使用者（confirm）。模型說要應徵不算數，使用者說好才算。
2. 雇主寫的職缺內文標成資料（<employer_text>），而且內文關不掉這個標籤。
3. 回合數有上限：模型一直呼叫工具時，成本和時間不會無限增加。
4. 每一步都記在 Trace 裡：評分看的是 Agent 做了什麼，不只是它最後說了什麼。

測試用的故障注入：lose_responses={"apply_job": 1} 讓第一次應徵真的送出，但模型收到的是逾時。
"""
from __future__ import annotations

import html
import json
import time
from dataclasses import asdict, dataclass, field
from typing import Callable

from agent.models import Model
from agent.prompts import system_prompt
from jobboard import bugs
from jobboard.board import JobBoard, ToolError

MAX_TURNS = 8
TURN_LIMIT_REPLY = "抱歉，這個要求我沒辦法在限定的步驟內完成，請把需求說得更具體一點再試一次。"
LOST_RESPONSE = "錯誤：連線逾時，沒有收到回應，不確定是否已經送出。"

TOOLS = [
    {
        "name": "search_jobs",
        "description": "搜尋開放中的職缺，最多回傳 10 筆。所有條件都可以省略。",
        "input_schema": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "關鍵字，比對職稱、標籤和內文；空白分隔的任一個字詞符合即可"},
                "city": {"type": "string", "description": "城市，例如「台北市」"},
                "min_monthly_salary": {"type": "integer", "description": "最低月薪（元）。職缺的最低薪資要大於或等於這個數字；面議視為 40,000"},
                "remote_only": {"type": "boolean", "description": "只要可遠端的職缺"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_job",
        "description": "取得一個職缺的完整內容，包含雇主寫的內文。",
        "input_schema": {
            "type": "object",
            "properties": {"job_id": {"type": "string", "description": "職缺編號，例如 J-102"}},
            "required": ["job_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_my_resume",
        "description": "取得目前使用者的履歷摘要（聯絡方式已遮蔽）。",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "apply_job",
        "description": "替使用者應徵一個職缺。系統送出前會先向使用者確認。",
        "input_schema": {
            "type": "object",
            "properties": {"job_id": {"type": "string", "description": "職缺編號，例如 J-102"}},
            "required": ["job_id"],
            "additionalProperties": False,
        },
    },
]
SCHEMAS = {t["name"]: t["input_schema"] for t in TOOLS}


def check_args(name: str, args: dict) -> None:
    """模型給的參數要符合工具的 schema；不符合就當成工具錯誤交還給模型，讓它自己修正。"""
    if name not in SCHEMAS:
        raise ToolError(f"沒有 {name} 這個工具")
    schema = SCHEMAS[name]
    unknown = sorted(set(args) - set(schema["properties"]))
    missing = sorted(set(schema.get("required", [])) - set(args))
    if unknown or missing:
        raise ToolError(f"{name} 的參數不對：多了 {unknown}，少了 {missing}")


@dataclass
class ToolCall:
    name: str
    input: dict
    output: str = ""
    is_error: bool = False
    confirmed: bool | None = None        # None：沒有問使用者
    response_lost: bool = False          # 工具執行了，但模型收到的是逾時


@dataclass
class Trace:
    prompt: str
    model: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    final_text: str = ""
    stop_reason: str | None = None
    stopped: str | None = None           # None：正常結束；turn_limit、refusal、max_tokens
    turns: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    elapsed_s: float = 0.0

    def calls(self, name: str) -> list[ToolCall]:
        return [c for c in self.tool_calls if c.name == name]

    def to_dict(self) -> dict:
        return asdict(self)


def decline(job: dict) -> bool:
    return False


class Agent:
    def __init__(self, model: Model, board: JobBoard, confirm: Callable[[dict], bool] = decline,
                 lose_responses: dict[str, int] | None = None, max_turns: int = MAX_TURNS):
        self.model = model
        self.board = board
        self.confirm = confirm                       # 預設不同意：沒人回答時，什麼都不送出
        self.lose_responses = dict(lose_responses or {})
        self.max_turns = max_turns

    def run(self, prompt: str) -> Trace:
        trace = Trace(prompt=prompt, model=self.model.name)
        messages: list[dict] = [{"role": "user", "content": prompt}]
        system = system_prompt()
        started = time.monotonic()
        while True:
            if trace.turns >= self.max_turns and not bugs.on("no_turn_limit"):
                trace.stopped, trace.final_text = "turn_limit", TURN_LIMIT_REPLY
                break
            response = self.model.respond(system=system, tools=TOOLS, messages=messages)
            trace.turns += 1
            self._count_usage(trace, response.usage)
            trace.stop_reason = response.stop_reason
            if response.stop_reason != "tool_use":
                trace.final_text = "".join(b.text for b in response.content if b.type == "text")
                if response.stop_reason in ("refusal", "max_tokens"):
                    trace.stopped = response.stop_reason
                break
            # 整個 content 原樣放回去（包含 thinking 區塊），下一回合模型才看得到自己的推理
            messages.append({"role": "assistant", "content": response.content})
            results = [self._call(block, trace) for block in response.content if block.type == "tool_use"]
            # 同一回合的所有工具結果放在同一則訊息裡（API 的規定）
            messages.append({"role": "user", "content": results})
        trace.elapsed_s = round(time.monotonic() - started, 3)
        return trace

    def _call(self, block, trace: Trace) -> dict:
        call = ToolCall(name=block.name, input=dict(block.input))
        trace.tool_calls.append(call)
        try:
            check_args(block.name, call.input)
            if block.name == "apply_job" and not bugs.on("no_confirmation"):
                job = self.board.get_job(call.input.get("job_id"))
                call.confirmed = bool(self.confirm(job))
                if not call.confirmed:
                    result = {"status": "declined_by_user", "job_id": job["job_id"],
                              "message": "使用者沒有同意，沒有送出應徵。"}
                    return self._result(block, call, json.dumps(result, ensure_ascii=False))
            result = getattr(self.board, block.name)(**call.input)
        except ToolError as e:
            return self._result(block, call, str(e), is_error=True)
        if self.lose_responses.get(block.name, 0) > 0:
            self.lose_responses[block.name] -= 1
            call.response_lost = True
            return self._result(block, call, LOST_RESPONSE, is_error=True)
        if block.name == "get_job" and not bugs.on("untrusted_unmarked"):
            result = {**result, "description": mark_untrusted(result["description"])}
        return self._result(block, call, json.dumps(result, ensure_ascii=False))

    @staticmethod
    def _result(block, call: ToolCall, output: str, is_error: bool = False) -> dict:
        call.output, call.is_error = output, is_error
        result = {"type": "tool_result", "tool_use_id": block.id, "content": output}
        if is_error:
            result["is_error"] = True
        return result

    @staticmethod
    def _count_usage(trace: Trace, usage) -> None:
        trace.input_tokens += usage.input_tokens
        trace.output_tokens += usage.output_tokens
        trace.cache_read_input_tokens += usage.cache_read_input_tokens or 0
        trace.cache_creation_input_tokens += usage.cache_creation_input_tokens or 0


def mark_untrusted(text: str) -> str:
    """把雇主寫的內文包進 <employer_text>。先跳脫 < 和 >，內文裡偽造的 </employer_text> 就關不掉標籤。"""
    return f"<employer_text>{html.escape(text, quote=False)}</employer_text>"
