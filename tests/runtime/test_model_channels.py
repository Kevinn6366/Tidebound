"""验证渠道切换持久化、请求快照与模型凭据隔离。"""
import asyncio
import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from src.tidebound.config import AgentSettings
from src.tidebound.runtime.session import ChatSession
from src.tidebound.storage.model_channel import ChannelSelection


def test_channel_snapshot_and_restart(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """执行中切换只作用于下一轮，且重启后仍选用中转。

    Args:
        tmp_path: 隔离持久化目录。
        monkeypatch: 替换 HTTP 边界，不访问真实渠道。
    """
    async def scenario() -> None:
        settings = AgentSettings(data_dir=tmp_path, context_limit=65536,
            base_url='https://silicon.test/v1', model='silicon-model', api_key='silicon-secret',
            relay_base_url='https://relay.test/v1', relay_model='relay-model', relay_api_key='relay-secret')
        service = ChatSession(settings)
        requests: list[tuple[str, str]] = []
        actual_client = httpx.AsyncClient

        def handle(request: httpx.Request) -> httpx.Response:
            requests.append((request.url.host, request.headers['authorization']))
            if not json.loads(request.content)['stream']:
                return httpx.Response(200, json={'choices': [{'message': {
                    'role': 'assistant', 'content': '欢迎回来。'}, 'finish_reason': 'stop'}]})
            if len(requests) == 1:
                service.channels.select(ChannelSelection(channel='codex789'))
                delta = {'tool_calls': [{'index': 0, 'id': 'clock', 'type': 'function',
                    'function': {'name': 'get_current_time', 'arguments': '{}'}}]}
                reason = 'tool_calls'
            else:
                delta, reason = {'content': '好的。'}, 'stop'
            return httpx.Response(200, text='data: ' + json.dumps({
                'choices': [{'delta': delta, 'finish_reason': reason}],
            }) + '\n\ndata: [DONE]\n\n', headers={'content-type': 'text/event-stream'})

        monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: actual_client(
            transport=httpx.MockTransport(handle), **kwargs))
        owner = str(uuid4())
        first = service.start(owner, str(uuid4()), '现在几点？')
        await service.active[owner].task
        assert first.status == 'completed', first.error
        assert requests == [('silicon.test', 'Bearer silicon-secret')] * 2
        second = service.start(owner, str(uuid4()), '知道了')
        await service.active[owner].task
        assert second.status == 'completed', second.error
        assert requests[-1] == ('relay.test', 'Bearer relay-secret')
        welcome = service.prepare_meet(owner, trigger='manual')
        await service.active[owner].task
        assert welcome is not None and welcome.status == 'completed'
        assert requests[-1] == ('silicon.test', 'Bearer silicon-secret')
        await service.close()
        restarted = ChatSession(settings)
        assert restarted.settings_for(owner).model == 'relay-model'
        assert 'secret' not in restarted.channels.store.path.read_text()
        await restarted.close()

    asyncio.run(scenario())


def test_search_workflow_uses_siliconflow_while_chat_uses_relay(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """搜索节点固定原始供应商的独立模型，主请求与跟进不受影响。

    Args:
        tmp_path: 隔离存储目录。
        monkeypatch: 替换搜索和模型 HTTP 请求。
    """
    async def search(query: str, key: str) -> dict[str, object]:
        return {'results': [{'title': '资料', 'url': 'https://example.org', 'description': '摘要'}]}

    monkeypatch.setattr('src.tidebound.tools.companion.operations.search_web', search)

    async def scenario() -> None:
        settings = AgentSettings(data_dir=tmp_path, context_limit=65536,
            base_url='https://silicon.test/v1', model='silicon-model', api_key='silicon-secret',
            relay_base_url='https://relay.test/v1', relay_model='relay-model', relay_api_key='relay-secret',
            search_api_key='search-secret')
        service = ChatSession(settings)
        service.channels.select(ChannelSelection(channel='codex789'))
        requests: list[tuple[str, str, str]] = []
        actual_client = httpx.AsyncClient

        def handle(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            requests.append((request.url.host, request.headers['authorization'], body['model']))
            reason = 'stop'
            if len(requests) == 1:
                delta = {'tool_calls': [{'index': 0, 'id': 'search', 'type': 'function',
                    'function': {'name': 'search_web', 'arguments': '{"query":"教程"}'}}]}
                reason = 'tool_calls'
            elif len(requests) == 2:
                delta = {'content': '能动手做点东西就很有趣呢。'}
            elif len(requests) == 3:
                delta = {'content': '{"summary":"想学编程","reason":"找入门资料"}'}
            elif len(requests) == 4:
                delta = {'content': '{"impression":"这份资料适合入门","uncertainty":"仅摘要","source_ids":[0]}'}
            else:
                delta = {'content': '这份资料看起来挺适合你。'}
            if not body['stream']:
                return httpx.Response(200, json={'choices': [{'message': {
                    'role': 'assistant', **delta}, 'finish_reason': reason}]})
            return httpx.Response(200, text='data: ' + json.dumps({
                'choices': [{'delta': delta, 'finish_reason': reason}],
            }) + '\n\ndata: [DONE]\n\n', headers={'content-type': 'text/event-stream'})

        monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: actual_client(
            transport=httpx.MockTransport(handle), **kwargs))
        owner = uuid4().hex
        record = service.start(owner, str(uuid4()), '查查入门资料', internet_enabled=True)
        await service.active[owner].task
        assert record.status == 'completed', record.error
        assert requests == [
            ('relay.test', 'Bearer relay-secret', 'relay-model'),
            ('silicon.test', 'Bearer silicon-secret', 'deepseek-ai/DeepSeek-V4-Flash'),
            ('silicon.test', 'Bearer silicon-secret', 'deepseek-ai/DeepSeek-V4-Flash'),
            ('silicon.test', 'Bearer silicon-secret', 'deepseek-ai/DeepSeek-V4-Flash'),
            ('relay.test', 'Bearer relay-secret', 'relay-model'),
            ('relay.test', 'Bearer relay-secret', 'relay-model'),
        ]
        assert service.channels.view().selected == 'codex789'
        await service.close()

    asyncio.run(scenario())
