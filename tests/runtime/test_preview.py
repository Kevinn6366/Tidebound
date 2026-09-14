"""验证真实供应商分片到达即更新预览，停止不提交临时正文。"""

import asyncio
import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from src.tidebound.config import AgentSettings
from src.tidebound.runtime.session import ChatSession


@pytest.mark.parametrize('stop_run', [False, True])
def test_live_preview_before_completion(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, stop_run: bool) -> None:
    """模型还未完成时预览已可读，且始终不落入执行记录的 preview 字段。

    Args:
        monkeypatch: 隔离供应商网络。
        tmp_path: 临时执行目录。
        stop_run: 是否在正文中途停止。
    """
    async def scenario() -> None:
        entered, release = asyncio.Event(), asyncio.Event()

        class DelayedStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b'data: {"choices":[{"delta":{"content":"hello"},"finish_reason":null}]}\n\n'
                entered.set()
                await release.wait()
                yield b'data: {"choices":[{"delta":{"content":" world"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'

        actual = httpx.AsyncClient

        def respond(request: httpx.Request) -> httpx.Response:
            """检查聊天无论 debug 开关都请求流式协议。

            Args:
                request: 实际模型请求。

            Returns:
                由测试信号控制结束的流。
            """
            assert json.loads(request.content)['stream'] is True
            return httpx.Response(200, stream=DelayedStream())

        monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: actual(transport=httpx.MockTransport(respond), **kw))
        service = ChatSession(AgentSettings(base_url='http://fixture', model='fixture', debug=False, data_dir=tmp_path))
        owner, run_id = uuid4().hex, str(uuid4())
        service.start(owner, run_id, 'hello')
        task = service.active[owner].task
        await entered.wait()
        assert service.get(owner, run_id).status == 'running'
        assert service.get(owner, run_id).preview == 'hello'
        assert service.records(owner)[0].preview == 'hello'
        assert service.store.list_runs(owner)[0].messages == []
        if stop_run:
            service.stop(owner, run_id)
        else:
            release.set()
        await task
        record = service.get(owner, run_id)
        assert record.preview == ''
        assert record.status == ('stopped' if stop_run else 'completed')
        if not stop_run:
            assert record.messages[-1].content == 'hello world'
        assert '"preview"' not in (tmp_path / owner / f'{run_id.replace("-", "")}.json').read_text()

    asyncio.run(scenario())
