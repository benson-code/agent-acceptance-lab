"""App 用的本機 API 伺服器：執行同一份 Agent（agent/harness.py）和求職平台（jobboard/），讓 App 操作。

    .venv/bin/uvicorn server.app:app --port 8430

App 不直接接模型。示範模式用假模型照劇本（server/scenarios.py），不用 API key；真模型模式需要
ANTHROPIC_API_KEY。不管哪種模式，工具、角色權限、確認、遮蔽和埋 bug 開關都是測試跑的那一份。

確認流程：harness 的 confirm 是同步呼叫，所以 Agent 在背景執行緒跑；遇到要確認的事就暫停，狀態變成
needs_confirmation，等 App 呼叫 POST /runs/{id}/confirm。App 在 confirm_timeout 秒內沒回答就當作不同意，
和 harness「沒人回答就不送出」的預設一致。

同一時間只允許一個執行（JobBoard 是一個 SQLite 連線）；上一個還在等確認時，新的執行回 409。
"""
from __future__ import annotations

import itertools
import json
import os
import threading
import time
import traceback
from dataclasses import asdict, dataclass, field

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from agent.harness import ROLE_TOOLS, Agent
from agent.models import ClaudeModel, ScriptedModel
from jobboard import bugs
from jobboard.board import JobBoard, Session
from server.scenarios import BY_ID, SCENARIOS

ACCOUNTS = ("U-001", "C-01", "C-02")           # App 上能切換的三個身分
CONFIRM_TIMEOUT_S = 60


@dataclass
class Run:
    id: str
    session: Session
    name: str
    prompt: str
    mode: str                                   # demo：照劇本；live：真模型
    scenario_id: str | None = None
    status: str = "running"                     # running → needs_confirmation → running … → done | error
    pending: dict | None = None
    confirmations: list[dict] = field(default_factory=list)
    error: str | None = None
    agent: Agent | None = None
    answer: bool | None = None
    started: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        trace = asdict(self.agent.trace) if self.agent and self.agent.trace else None
        for call in (trace or {}).get("tool_calls", []):
            # App 照模型給的順序顯示參數（Swift 的 Dictionary 沒有順序）
            call["input_text"] = json.dumps(call["input"], ensure_ascii=False)
        return {"id": self.id, "mode": self.mode, "scenario_id": self.scenario_id, "prompt": self.prompt,
                "account": {"role": self.session.role, "user_id": self.session.user_id, "name": self.name},
                "status": self.status, "pending": self.pending, "confirmations": self.confirmations,
                "error": self.error, "trace": trace}


class StartRun(BaseModel):
    scenario_id: str | None = None
    user_id: str | None = None                  # 真模型模式：誰在說話
    prompt: str | None = None


class Answer(BaseModel):
    approve: bool


class BugSwitches(BaseModel):
    on: list[str]


def create_app(confirm_timeout: float = CONFIRM_TIMEOUT_S) -> FastAPI:
    api = FastAPI(title="agent-acceptance-lab", version="1.0")
    state = {"board": JobBoard(), "runs": {}, "active": None}
    api.state.data = state                      # 測試用：直接看資料庫，確認 App 看到的和資料庫一致
    changed = threading.Condition()             # 執行狀態一變就通知等待中的 GET /runs/{id}?wait=
    ids = itertools.count(1)

    def account(user_id: str) -> tuple[Session, str]:
        board = state["board"]
        if user_id in board.companies:
            return Session("employer", user_id), board.companies[user_id]["name"]
        if user_id in board.seekers:
            return Session("seeker", user_id), board.seekers[user_id]["name"]
        raise HTTPException(404, f"沒有 {user_id} 這個帳號")

    def busy() -> Run | None:
        run = state["active"]
        return run if run and run.status in ("running", "needs_confirmation") else None

    def update(run: Run, **values) -> None:
        with changed:
            for k, v in values.items():
                setattr(run, k, v)
            changed.notify_all()

    def execute(run: Run) -> None:
        def confirm(action: dict) -> bool:
            update(run, status="needs_confirmation", pending=action, answer=None)
            with changed:
                answered = changed.wait_for(lambda: run.answer is not None, timeout=confirm_timeout)
            approve = bool(run.answer) if answered else False
            run.confirmations.append({**action, "approved": approve, "timed_out": not answered})
            update(run, status="running", pending=None)
            return approve

        run.agent.confirm = confirm
        try:
            run.agent.run(run.prompt)
            update(run, status="done")
        except Exception as e:  # 劇本寫錯、模型 API 出錯：記在執行裡給 App 看，伺服器不能跟著掛
            traceback.print_exc()
            update(run, status="error", error=f"{type(e).__name__}: {e}")

    @api.get("/health")
    def health() -> dict:
        return {"ok": True, "live_available": bool(os.environ.get("ANTHROPIC_API_KEY"))}

    @api.get("/accounts")
    def accounts() -> list[dict]:
        out = []
        for user_id in ACCOUNTS:
            session, name = account(user_id)
            out.append({"role": session.role, "user_id": user_id, "name": name,
                        "tools": list(ROLE_TOOLS[session.role]),
                        "scenarios": [s.to_dict() for s in SCENARIOS if s.user_id == user_id]})
        return out

    @api.get("/bugs")
    def get_bugs() -> list[dict]:
        return [{"key": k, "label": label, "side": side, "on": bugs.on(k)} for k, (label, side) in bugs.LABELS.items()]

    @api.put("/bugs")
    def put_bugs(body: BugSwitches) -> list[dict]:
        try:
            bugs.set_active(body.on)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        return get_bugs()

    @api.post("/reset")
    def reset() -> dict:
        if busy():
            raise HTTPException(409, "還有執行在跑，先回答或等它結束")
        state["board"], state["runs"], state["active"] = JobBoard(), {}, None
        return {"ok": True}

    @api.post("/runs", status_code=201)
    def start(body: StartRun) -> dict:
        if busy():
            raise HTTPException(409, "上一個執行還在等確認，先回答它")
        if body.scenario_id:
            scenario = BY_ID.get(body.scenario_id)
            if scenario is None:
                raise HTTPException(404, f"沒有 {body.scenario_id} 這個情境")
            session, name = account(scenario.user_id)
            model, prompt, mode = ScriptedModel(scenario.script()), scenario.prompt, "demo"
        else:
            if not (body.user_id and body.prompt and body.prompt.strip()):
                raise HTTPException(422, "要給 scenario_id，或給 user_id 和 prompt")
            if not os.environ.get("ANTHROPIC_API_KEY"):
                raise HTTPException(400, "真模型模式需要在伺服器設定 ANTHROPIC_API_KEY")
            session, name = account(body.user_id)
            model = ClaudeModel(os.environ.get("AGENT_MODEL", "claude-opus-5-5"), os.environ.get("AGENT_EFFORT", "medium"))
            prompt, mode = body.prompt.strip(), "live"
        run = Run(id=f"run_{next(ids):04d}", session=session, name=name, prompt=prompt, mode=mode,
                  scenario_id=body.scenario_id)
        run.agent = Agent(model, state["board"], session=session)
        state["runs"][run.id], state["active"] = run, run
        threading.Thread(target=execute, args=(run,), daemon=True, name=run.id).start()
        return run.to_dict()

    @api.get("/runs/{run_id}")
    def get_run(run_id: str, wait: float = Query(0, ge=0, le=20)) -> dict:
        """wait > 0：等到執行不是 running（結束或需要確認）再回，最多 wait 秒。App 用它代替一直輪詢。"""
        run = state["runs"].get(run_id)
        if run is None:
            raise HTTPException(404, f"沒有 {run_id}")
        if wait:
            with changed:
                changed.wait_for(lambda: run.status != "running", timeout=wait)
        return run.to_dict()

    @api.post("/runs/{run_id}/confirm")
    def answer(run_id: str, body: Answer) -> dict:
        run = state["runs"].get(run_id)
        if run is None:
            raise HTTPException(404, f"沒有 {run_id}")
        with changed:
            if run.status != "needs_confirmation" or run.answer is not None:
                raise HTTPException(409, "這個執行現在沒有在等確認")
            run.answer = body.approve
            changed.notify_all()
            # 等 Agent 收到答案、繼續往下跑（或結束），回傳的就是之後的狀態
            changed.wait_for(lambda: run.status != "needs_confirmation", timeout=5)
        return get_run(run_id, wait=5)

    return api


app = create_app()
