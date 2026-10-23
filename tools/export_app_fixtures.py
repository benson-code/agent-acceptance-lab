"""產生 iOS 單元測試用的 JSON（ios/JobAgentTests/Fixtures/）：用真的伺服器跑情境，存下 App 會收到的回應。

    .venv/bin/python -m tools.export_app_fixtures

伺服器的回應格式改了就重跑一次，App 的解碼測試會告訴你哪裡對不上。
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from server.app import create_app

OUT = Path(__file__).resolve().parent.parent / "ios" / "JobAgentTests" / "Fixtures"


def save(name: str, data) -> None:
    (OUT / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{name}.json")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    client = TestClient(create_app(confirm_timeout=5))
    client.put("/bugs", json={"on": []})

    def run(scenario: str, approve: bool | None = None) -> dict:
        r = client.post("/runs", json={"scenario_id": scenario}).json()
        r = client.get(f"/runs/{r['id']}", params={"wait": 10}).json()
        if approve is not None and r["status"] == "needs_confirmation":
            r = client.post(f"/runs/{r['id']}/confirm", json={"approve": approve}).json()
        return r

    save("accounts", client.get("/accounts").json())
    save("bugs", client.get("/bugs").json())
    save("run_blocked", run("morning-other"))
    save("run_untrusted", run("morning-review"))
    save("run_pending", run("seeker-apply"))
    client.post(f"/runs/{client.app.state.data['active'].id}/confirm", json={"approve": False})
    save("run_declined", run("seeker-apply", approve=False))
    client.put("/bugs", json={"on": ["untrusted_unmarked"]})
    save("run_unmarked", run("seeker-injection", approve=False))
    client.put("/bugs", json={"on": ["pii_before_interview"]})
    save("run_contact", run("morning-contact"))
    client.put("/bugs", json={"on": []})


if __name__ == "__main__":
    main()
