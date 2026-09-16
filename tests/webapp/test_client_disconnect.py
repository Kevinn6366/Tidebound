"""验证客户端断连不会覆盖界面配置或作为未处理异常抛出。"""
import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.types import Message, Scope

from tests.webapp.test_auth_console import CREDENTIALS, make_app


@pytest.mark.parametrize('partial_body', [b'', b'{"value":'])
def test_interrupted_settings_write_preserves_saved_data(tmp_path: Path, partial_body: bytes) -> None:
    """模拟 ASGI 在 JSON 请求体尚未收完时收到断连事件。

    Args:
        tmp_path: 隔离账号与界面配置的临时目录。
        partial_body: 断连前已接收的请求体片段。
    """
    app = make_app(tmp_path)
    client = TestClient(app)
    client.post('/api/auth/setup', json=CREDENTIALS)
    path = '/api/userdata/preview/core/disconnect-test'
    original = {'value': '保留原配置'}
    assert client.put(path, json=original).status_code == 200
    events: list[Message] = []

    async def interrupted_request() -> None:
        """通过实际中间件与路由处理分段请求及断连事件。"""
        incoming: list[Message] = [
            {'type': 'http.request', 'body': partial_body, 'more_body': True},
            {'type': 'http.disconnect'},
        ]

        async def receive() -> Message:
            """依次交付未完成的正文和连接中断事件。

            Returns:
                当前 ASGI 请求事件；断开后持续返回断连事件。
            """
            return incoming.pop(0) if incoming else {'type': 'http.disconnect'}

        async def send(message: Message) -> None:
            """记录服务端响应以确认没有误报保存成功。

            Args:
                message: 应用发出的 ASGI 响应事件。
            """
            events.append(message)

        scope: Scope = {
            'type': 'http', 'asgi': {'version': '3.0', 'spec_version': '2.3'},
            'http_version': '1.1', 'method': 'PUT', 'scheme': 'http',
            'path': path, 'raw_path': path.encode(), 'query_string': b'', 'root_path': '',
            'headers': [(b'host', b'testserver'), (b'content-type', b'application/json'),
                        (b'cookie', f'tidebound_session={client.cookies.get("tidebound_session")}'.encode())],
            'client': ('127.0.0.1', 12345), 'server': ('testserver', 80),
        }
        await app(scope, receive, send)

    asyncio.run(interrupted_request())
    assert [event['status'] for event in events if event['type'] == 'http.response.start'] == [499]
    assert client.get(path).json() == original
    assert not list((tmp_path / 'ui').rglob('*.tmp'))
    assert client.put(path, json={'value': '后续保存正常'}).status_code == 200
    assert client.get(path).json() == {'value': '后续保存正常'}
