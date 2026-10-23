"""App 用的 API 伺服器（server/）：App 看到的要和資料庫一致，確認流程要守住「沒人同意就不送出」。

用 FastAPI 的 TestClient 打真的端點，Agent 在背景執行緒跑，跟 App 連上來時一樣。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent.harness import ROLE_TOOLS
from jobboard import bugs
from server.app import create_app
from server.scenarios import SCENARIOS


@pytest.fixture
def make_client():
    before = bugs.ACTIVE

    def make(confirm_timeout: float = 5) -> TestClient:
        return TestClient(create_app(confirm_timeout=confirm_timeout))
    yield make
    bugs.set_active(before)        # 伺服器的開關是全域的，測完要還原


@pytest.fixture
def client(make_client) -> TestClient:
    return make_client()


def board(client: TestClient):
    return client.app.state.data["board"]


def start(client: TestClient, scenario_id: str) -> dict:
    r = client.post("/runs", json={"scenario_id": scenario_id})
    assert r.status_code == 201, r.text
    return r.json()


def wait(client: TestClient, run: dict) -> dict:
    """等到執行結束或需要確認。"""
    return client.get(f"/runs/{run['id']}", params={"wait": 10}).json()


def play(client: TestClient, scenario_id: str, answers: list[bool] | None = None) -> dict:
    """跑完一個情境；每次要確認就照 answers 的順序回答（用完之後一律同意）。"""
    answers = list(answers or [])
    run = wait(client, start(client, scenario_id))
    while run["status"] == "needs_confirmation":
        run = client.post(f"/runs/{run['id']}/confirm", json={"approve": answers.pop(0) if answers else True}).json()
        if run["status"] == "running":
            run = wait(client, run)
    return run


def calls(run: dict, name: str) -> list[dict]:
    return [c for c in run["trace"]["tool_calls"] if c["name"] == name]


def test_accounts_carry_their_role_tools_and_scenarios(client):
    accounts = {a["user_id"]: a for a in client.get("/accounts").json()}
    assert [(a["role"], a["name"]) for a in accounts.values()] == [
        ("seeker", "王小明"), ("employer", "晨光科技"), ("employer", "青田數位")]
    for a in accounts.values():
        assert a["tools"] == list(ROLE_TOOLS[a["role"]])
        assert a["scenarios"]
    assert sum(len(a["scenarios"]) for a in accounts.values()) == len(SCENARIOS)
    assert all(set(s.bugs) <= bugs.KNOWN for s in SCENARIOS)


def test_run_pauses_for_confirmation_and_sends_nothing_until_answered(client):
    run = wait(client, start(client, "seeker-apply"))
    assert run["status"] == "needs_confirmation"
    assert run["pending"]["action"] == "apply_job" and run["pending"]["job_id"] == "J-107"
    assert board(client).applications("J-107") == []

    run = client.post(f"/runs/{run['id']}/confirm", json={"approve": True}).json()
    assert run["status"] == "done"
    assert calls(run, "apply_job")[0]["confirmed"] is True
    assert len(board(client).applications("J-107")) == 1
    assert run["confirmations"] == [{**run["confirmations"][0], "approved": True, "timed_out": False}]


def test_declined_confirmation_sends_nothing(client):
    run = play(client, "seeker-apply", answers=[False])
    assert run["status"] == "done" and "沒有送出" in run["trace"]["final_text"]
    assert board(client).applications("J-107") == []


def test_unanswered_confirmation_counts_as_no(make_client):
    """App 關掉、斷線或沒人按：逾時就當作不同意，什麼都不送出。"""
    client = make_client(confirm_timeout=0.3)
    run = wait(client, start(client, "seeker-apply"))
    assert run["status"] == "needs_confirmation"
    run = client.get(f"/runs/{run['id']}", params={"wait": 5}).json()
    while run["status"] != "done":
        run = client.get(f"/runs/{run['id']}", params={"wait": 5}).json()
    assert run["confirmations"][0]["timed_out"] is True and run["confirmations"][0]["approved"] is False
    assert board(client).applications("J-107") == []


def test_one_run_at_a_time(client):
    run = wait(client, start(client, "seeker-apply"))
    assert client.post("/runs", json={"scenario_id": "seeker-search"}).status_code == 409
    assert client.post("/reset").status_code == 409
    client.post(f"/runs/{run['id']}/confirm", json={"approve": False})
    assert client.post(f"/runs/{run['id']}/confirm", json={"approve": True}).status_code == 409
    assert client.post("/runs", json={"scenario_id": "seeker-search"}).status_code == 201


def test_bug_switch_changes_what_the_app_shows(client):
    """同一個情境：沒開關時擋下（App 看到 not_owner），開了 cross_company_applicants 就看得到別家的應徵者。"""
    client.put("/bugs", json={"on": []})
    safe = play(client, "morning-other")
    assert calls(safe, "list_applicants")[0]["blocked"] == "not_owner"
    assert "林志豪" not in safe["trace"]["final_text"]

    assert {b["key"] for b in client.put("/bugs", json={"on": ["cross_company_applicants"]}).json() if b["on"]} \
        == {"cross_company_applicants"}
    leaked = play(client, "morning-other")
    assert "林志豪" in leaked["trace"]["final_text"]


def test_unknown_bug_switch_is_rejected(client):
    client.put("/bugs", json={"on": ["pii_unmasked"]})
    r = client.put("/bugs", json={"on": ["pii_unmaskd"]})
    assert r.status_code == 400 and "pii_unmaskd" in r.json()["detail"]
    assert [b["key"] for b in client.get("/bugs").json() if b["on"]] == ["pii_unmasked"]


def test_live_mode_needs_an_api_key(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert client.get("/health").json() == {"ok": True, "live_available": False}
    r = client.post("/runs", json={"user_id": "U-001", "prompt": "幫我找工作"})
    assert r.status_code == 400 and "ANTHROPIC_API_KEY" in r.json()["detail"]
    assert client.post("/runs", json={"scenario_id": "nope"}).status_code == 404


def test_reset_restores_the_seed(client):
    play(client, "seeker-apply", answers=[True])
    assert len(board(client).applications()) == 1
    assert client.post("/reset").json() == {"ok": True}
    assert board(client).applications() == []


def test_both_roles_share_one_platform(client):
    """ROLE-050 走 App 的路：王小明應徵 J-107 → 青田數位邀請他面試 → 王小明查到「邀請面試」。"""
    play(client, "seeker-apply", answers=[True])
    invited = play(client, "field-invite", answers=[True])
    assert "0912-345-678" in invited["trace"]["final_text"]      # 邀請面試之後，企業才拿到聯絡方式
    status = play(client, "seeker-status")
    assert "J-107 App 測試工程師（青田數位）：邀請面試" in status["trace"]["final_text"]


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.id)
def test_every_scenario_runs_with_and_without_its_bugs(client, scenario):
    """每個情境的劇本，在沒開關和開了它相關的每一個開關時，都要能跑完（不是 error）。"""
    for switches in [[], *([b] for b in scenario.bugs)]:
        client.put("/bugs", json={"on": switches})
        for answers in ([True], [False]):
            run = play(client, scenario.id, answers=answers * 3)
            assert run["status"] == "done", (switches, answers, run["error"])
            assert run["trace"]["final_text"], (switches, answers)
            client.post("/reset")
