"""验证 console 快照等于实际 HTTP 正文且不会进入模型历史。"""

import asyncio
import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from src.tidebound.config import AgentSettings
from src.tidebound.runtime.session import ChatSession
from src.tidebound.storage.model_requests import ModelRequestStore


@pytest.mark.parametrize("debug", [False, True])
def test_snapshots_match_http_body(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, debug: bool) -> None:
    """终端 debug 开关均保留精确的流式请求正文，包括调用后的一次性注入。

    Args:
        monkeypatch: 替换模型 HTTP 网络。
        tmp_path: 隔离请求与执行记录。
        debug: 是否同时输出终端调试日志。
    """
    bodies: list[dict[str, object]] = []
    actual = httpx.AsyncClient

    def respond(request: httpx.Request) -> httpx.Response:
        """捕获正文，先请求工具再结束回复。

        Args:
            request: 模型适配器实际发送的请求。

        Returns:
            与当前模式对应的受控回复。
        """
        bodies.append(json.loads(request.content))
        message: dict[str, object] = {"role": "assistant", "content": "完成"}
        finish = "stop"
        if len(bodies) == 1:
            message = {"role": "assistant", "content": "", "tool_calls": [
                {"id": "call-time", "type": "function", "function": {"name": "get_current_time", "arguments": "{}"}},
            ]}
            finish = "tool_calls"
        if bodies[-1]["stream"]:
            if "tool_calls" in message:
                message["tool_calls"][0]["index"] = 0
            chunk = {"choices": [{"delta": message, "finish_reason": finish}]}
            return httpx.Response(200, text="data: " + json.dumps(chunk) + "\n\ndata: [DONE]\n\n")
        return httpx.Response(200, json={"choices": [{"message": message, "finish_reason": finish}]})

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: actual(transport=httpx.MockTransport(respond), **kw))

    async def scenario() -> None:
        settings = AgentSettings(base_url="http://fixture/v1", model="fixture", api_key="secret-api-key",
                                 data_dir=tmp_path, debug=debug)
        service = ChatSession(settings)
        owner, run_id = uuid4().hex, str(uuid4())
        service.start(owner, run_id, "现在几点")
        await service.active[owner].task
        assert service.get(owner, run_id).status == "completed"
        store = ModelRequestStore(tmp_path)
        summaries = sorted(store.list_requests(), key=lambda item: item.step)
        assert [item.step for item in summaries] == [1, 2]
        assert all(item.owner == owner and item.run_id == run_id for item in summaries)
        assert [store.get(item.request_id).body for item in summaries] == bodies
        assert store.get(summaries[0].request_id).injection == ""
        assert "先获取当前时间再回答" in store.get(summaries[1].request_id).injection
        rule = "先获取当前时间再回答"
        assert rule not in bodies[0]["messages"][0]["content"]
        assert rule in bodies[1]["messages"][0]["content"]
        assert "secret-api-key" not in "".join(path.read_text() for path in store.root.glob("*.json"))
        assert all(rule not in message.content for message in service.get(owner, run_id).messages)
        restarted = ModelRequestStore(tmp_path)
        assert len(restarted.list_requests()) == 2

    asyncio.run(scenario())


def test_run_group_pagination_keeps_every_call(tmp_path: Path) -> None:
    """以对话分页，同账号的不同轮次及不同账号的同 ID 分别成组。

    Args:
        tmp_path: 隔离快照目录。
    """
    from src.tidebound.storage.model_requests import request_run, request_step

    store = ModelRequestStore(tmp_path)
    owner, other, run_id = uuid4().hex, uuid4().hex, str(uuid4())
    for account, run, count in [(owner, run_id, 3), (owner, str(uuid4()), 1), (other, run_id, 2)]:
        run_token = request_run.set((account, run))
        try:
            for step in range(1, count + 1):
                step_token = request_step.set(step)
                try:
                    store.save({"model": "fixture", "messages": [{"role": "user", "content": "本轮问题"}]})
                finally:
                    request_step.reset(step_token)
        finally:
            request_run.reset(run_token)
    pages = [store.list_request_runs(offset, 1) for offset in range(3)]
    assert [len(page[0].requests) for page in pages] == [2, 1, 3]
    assert [request.step for request in pages[2][0].requests] == [1, 2, 3]
    assert pages[2][0].user_content == "本轮问题"
    assert store.list_request_runs(3, 1) == []
