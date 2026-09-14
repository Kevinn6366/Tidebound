"""验证 HTTP 适配边界及非法供应商响应。"""
import asyncio
import json

import httpx
import pytest

from src.config import AgentSettings
from src.errors import AgentError
from src.llm import ChatCompletionsClient
from src.runtime.types import Message


@pytest.mark.parametrize('payload,status,code', [
    ({'choices': []}, 200, 'invalid_model_response'),
    ({'error': 'secret'}, 401, 'model_http_error'),
    ({'choices': [{'message': {'role': 'user', 'content': 'bad'}, 'finish_reason': 'stop'}]}, 200, 'invalid_model_response'),
    ({'choices': [{'message': {'role': 'assistant', 'content': 'answer'}, 'finish_reason': 'stop'}]}, 200, None),
])
def test_http_contract(monkeypatch: pytest.MonkeyPatch, payload: dict[str, object], status: int, code: str | None) -> None:
    """检查请求正文、凭据边界和响应校验。

    Args:
        monkeypatch: 临时替换 HTTP 连接工厂。
        payload: 模拟供应商响应正文。
        status: 供应商 HTTP 状态。
        code: 预期安全错误码，空表示成功。
    """
    actual_client = httpx.AsyncClient
    def handle(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == 'http://fixture/v1/chat/completions'
        body = json.loads(request.content)
        assert body['messages'] == [{'role': 'system', 'content': 'atri'}, {'role': 'user', 'content': 'hello'}]
        assert body['stream'] is False
        assert request.headers['Authorization'] == 'Bearer test-only'
        return httpx.Response(status, json=payload)
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: actual_client(transport=httpx.MockTransport(handle), **kwargs))
    async def scenario() -> None:
        model = ChatCompletionsClient(AgentSettings(base_url='http://fixture/v1', model='fixture', api_key='test-only'))
        if code:
            with pytest.raises(AgentError) as error:
                await model.complete('atri', [Message(role='user', content='hello')], [])
            assert error.value.code == code
            assert 'secret' not in str(error.value)
        else:
            reply = await model.complete('atri', [Message(role='user', content='hello')], [])
            assert reply.message.content == 'answer'
    asyncio.run(scenario())
