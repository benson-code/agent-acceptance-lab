"""接真模型的那一段，在沒有 API key 的情況下也要測：SDK 指向本機一個假的 Messages API，
檢查送出去的請求長什麼樣、收到的回應有沒有被正確解讀。這樣真的跑評測時，花的錢不會浪費在格式錯誤上。
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import anthropic
import pytest

from agent.harness import TOOLS, Agent
from agent.models import ClaudeModel
from evals.judge import Judge


class FakeMessagesAPI:
    def __init__(self, replies: list[dict]):
        self.replies = iter(replies)
        self.requests: list[dict] = []
        api = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                api.requests.append({"path": self.path, "body": body})
                data = json.dumps(next(api.replies)).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.client = anthropic.Anthropic(api_key="test-key", base_url=f"http://127.0.0.1:{self.server.server_port}",
                                          max_retries=0)

    def close(self):
        self.server.shutdown()


def message(content: list[dict], stop_reason: str, **usage) -> dict:
    return {"id": "msg_test", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
            "content": content, "stop_reason": stop_reason, "stop_sequence": None,
            "usage": {"input_tokens": 100, "output_tokens": 20, **usage}}


@pytest.fixture
def api_with(request):
    apis = []

    def make(replies):
        api = FakeMessagesAPI(replies)
        apis.append(api)
        return api
    yield make
    for api in apis:
        api.close()


def test_agent_request_and_tool_loop_through_the_sdk(board, api_with):
    api = api_with([
        message([{"type": "thinking", "thinking": "", "signature": "sig"},
                 {"type": "tool_use", "id": "toolu_1", "name": "search_jobs", "input": {"keyword": "Appium"}}],
                "tool_use", cache_read_input_tokens=50),
        message([{"type": "text", "text": "找到 J-107。"}], "end_turn"),
    ])
    trace = Agent(ClaudeModel("claude-opus-5-5", "medium", api.client), board).run("找 Appium 職缺")

    first, second = (r["body"] for r in api.requests)
    assert api.requests[0]["path"] == "/v1/messages"
    assert first["model"] == "claude-opus-5-5" and first["output_config"] == {"effort": "medium"}
    assert first["tools"] == TOOLS and "求職助理" in first["system"]
    assert first["cache_control"] == {"type": "ephemeral"}
    # 第二回合：thinking 區塊原樣送回，工具結果對應到 toolu_1
    assert second["messages"][1]["content"][0] == {"type": "thinking", "thinking": "", "signature": "sig"}
    assert second["messages"][2]["content"][0]["tool_use_id"] == "toolu_1"
    assert trace.final_text == "找到 J-107。"
    assert (trace.input_tokens, trace.output_tokens, trace.cache_read_input_tokens) == (200, 40, 50)


def test_judge_request_and_verdict(api_with):
    api = api_with([message([{"type": "text", "text": json.dumps({"verdict": "fail", "reason": "說已應徵，但使用者不同意"})}],
                            "end_turn")])
    check = Judge("claude-opus-5-5", api.client).grade("- 沒有說已經應徵", "幫我應徵 J-102", "(log)", "已應徵")
    body = api.requests[0]["body"]
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["output_config"]["format"]["schema"]["required"] == ["verdict", "reason"]
    assert not check.passed and "使用者不同意" in check.detail


def test_judge_that_does_not_finish_is_a_fail(api_with):
    api = api_with([message([], "refusal")])
    check = Judge("claude-opus-5-5", api.client).grade("-", "-", "-", "-")
    assert not check.passed and "refusal" in check.detail
