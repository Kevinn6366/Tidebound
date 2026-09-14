"""验证终端思考流、工具分片与不完整流的提交边界。"""
import asyncio
import json

import httpx
import pytest

from src.config import AgentSettings
from src.errors import AgentError
from src.llm import ChatCompletionsClient, wire_messages
from src.runtime.types import Message


def test_debug_stream(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """分片重组后保留思考，终端不打印请求密钥或系统提示词。

    Args:
        monkeypatch: 隔离真实网络连接。
        capsys: 捕获终端输出。
    """
    chunks = [
        {'choices': [{'delta': {'role': 'assistant', 'reasoning_content': '先查'}, 'finish_reason': None}]},
        {'choices': [{'delta': {'reasoning_content': '时间', 'tool_calls': [{'index': 0, 'id': 'call-1', 'type': 'function', 'function': {'name': 'get_current_time', 'arguments': '{'}}]}, 'finish_reason': None}]},
        {'choices': [{'delta': {'tool_calls': [{'index': 0, 'function': {'arguments': '}'}}]}, 'finish_reason': 'tool_calls'}]},
        {'choices': [], 'usage': {'total_tokens': 10}},
    ]
    stream = ': heartbeat\n\n' + ''.join('data: '+json.dumps(c)+'\n\n' for c in chunks) + 'data: [DONE]\n\n'
    actual = httpx.AsyncClient
    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body['stream'] is True
        assert body['reasoning_effort'] == 'low'
        return httpx.Response(200, text=stream, headers={'content-type': 'text/event-stream'})
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: actual(transport=httpx.MockTransport(handle), **kw))
    async def scenario() -> None:
        client = ChatCompletionsClient(AgentSettings(base_url='http://fixture', model='test', api_key='private-key', debug=True, reasoning_effort='low'))
        reply = await client.complete('private-system', [Message(role='user', content='几点')], [])
        assert reply.message.reasoning_content == '先查时间'
        assert reply.message.tool_calls[0].arguments == '{}'
        assert reply.message.tool_calls[0].id == 'call-1'
        assert wire_messages('system', [reply.message])[1]['reasoning_content'] == '先查时间'
    asyncio.run(scenario())
    output = capsys.readouterr().err
    assert '先查时间' in output
    assert 'private-key' not in output
    assert 'private-system' not in output


@pytest.mark.parametrize('stream', [
    'data: {"choices":[{"delta":{"content":"半段"},"finish_reason":null}]}\n\n',
    'data: {"error":{"message":"secret"}}\n\ndata: [DONE]\n\n',
    'data: {"choices":[{"delta":{"content":"half"},"finish_reason":"stop"}]}\n\n',
])
def test_incomplete_stream_fails(monkeypatch: pytest.MonkeyPatch, stream: str) -> None:
    """缺失终止标记或供应商错误不能被当成完整回复。

    Args:
        monkeypatch: 隔离网络。
        stream: 无效的 SSE 事件序列。
    """
    actual = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: actual(transport=httpx.MockTransport(lambda _: httpx.Response(200, text=stream)), **kw))
    async def scenario() -> None:
        with pytest.raises(AgentError) as error:
            await ChatCompletionsClient(AgentSettings(base_url='http://fixture', debug=True)).complete('s', [], [])
        assert error.value.code == 'invalid_model_response'
    asyncio.run(scenario())
