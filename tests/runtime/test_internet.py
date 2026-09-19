"""公网访问保护、真实供应商协议适配及兴趣去重的受控验证。"""
import asyncio
import json
import socket

import httpx
import pytest

from src.tidebound.storage.companion import CompanionState, Interest
from src.tidebound.tools.internet import client
from src.tidebound.tools.internet.interest_updates import check_interest_updates


@pytest.mark.parametrize('address', ['127.0.0.1', '10.0.0.1', '169.254.169.254', '::1', 'fc00::1', '100.64.0.1'])
def test_private_dns_is_rejected(monkeypatch: pytest.MonkeyPatch, address: str) -> None:
    """即使 URL 看起来是域名，也拒绝解析后的非公网地址。"""
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: [(2, 1, 6, '', (address, 80))])
    with pytest.raises(ValueError, match='非公网'):
        client.fetch_public('http://example.com')


@pytest.mark.parametrize('url', ['file:///etc/passwd', 'http://user:pass@example.com',
                               'http://example.com:8080', 'http://example.com/\r\nHost: internal'])
def test_unsafe_url_never_connects(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    """协议、凭据、端口及请求头注入在联网前被拒绝。"""
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError('不得开始连接')
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    with pytest.raises(ValueError):
        client.fetch_public(url)


def test_redirect_rechecks_dns_and_pins_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    """首跳直连已校验 IP，跳往内部地址时不得建立第二条连接。"""
    connections = []
    class Sock:
        def close(self) -> None:
            pass
    def connect(address: tuple[str, int], **kwargs: object) -> Sock:
        connections.append(address)
        return Sock()
    class Response:
        status = 302
        def getheader(self, name: str, default: str | None = None) -> str | None:
            return 'http://internal.test/' if name == 'Location' else default
    class Connection:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.sock = None
        def request(self, *args: object, **kwargs: object) -> None:
            pass
        def getresponse(self) -> Response:
            return Response()
        def close(self) -> None:
            pass
    monkeypatch.setattr(socket, 'getaddrinfo', lambda host, *a, **k:
                        [(2, 1, 6, '', ('93.184.216.34' if host == 'example.com' else '127.0.0.1', 80))])
    monkeypatch.setattr(socket, 'create_connection', connect)
    monkeypatch.setattr(client.http.client, 'HTTPConnection', Connection)
    with pytest.raises(ValueError, match='非公网'):
        client.fetch_public('http://example.com', {'Authorization': 'Bearer secret'})
    assert connections == [('93.184.216.34', 80)]


def test_provider_adapters_and_interest_dedup(monkeypatch: pytest.MonkeyPatch) -> None:
    """检查搜索来源、天气候选、单位和兴趣检查状态，缺少配置不推进游标。"""
    monkeypatch.setattr(client, 'fetch_bocha', bocha_fixture)
    requests = []
    def fetch(url: str, headers: dict[str, str] | None = None) -> client.WebResponse:
        requests.append((url, headers))
        if 'bocha.cn' in url:
            body = {'code': 200, 'data': {'webPages': {'value': [
                {'name': '更新', 'url': 'https://example.com/news', 'summary': '内容'}]}}}
        elif 'geocoding' in url:
            body = {'results': [{'name': '同名地点', 'latitude': 1, 'longitude': 2},
                                {'name': '另一个地点', 'latitude': 3, 'longitude': 4}]}
        else:
            body = {'timezone': 'Asia/Shanghai', 'current': {'temperature_2m': 20},
                    'current_units': {'temperature_2m': '°C'}, 'daily': {}, 'daily_units': {}}
        return client.WebResponse(url, 'application/json', json.dumps(body).encode())
    monkeypatch.setattr(client, 'fetch_public', fetch)
    async def scenario() -> None:
        result = await client.search_web('游戏 & 更新', 'secret')
        assert result['results'][0]['url'] == 'https://example.com/news'
        assert requests[0] == (client.BOCHA_SEARCH_URL, {'Authorization': 'Bearer secret'})
        assert 'secret' not in json.dumps(result)
        weather = await client.get_weather('同名地点', None, None)
        assert weather['requires_location_confirmation']
        weather = await client.get_weather('确认地点', 1.0, 2.0)
        assert weather['current_units']['temperature_2m'] == '°C'
        state = CompanionState(interests=[Interest(id='i', topic='游戏', source_run_id='r', evidence='我喜欢游戏')])
        assert 'error' in await check_interest_updates(state, 'i', '')
        assert state.interests[0].checked_at is None
        assert len((await check_interest_updates(state, 'i', 'secret'))['results']) == 1
        assert (await check_interest_updates(state, 'i', 'secret'))['results'] == []
    asyncio.run(scenario())


def test_webpage_extraction_is_bounded_and_drops_scripts(monkeypatch: pytest.MonkeyPatch) -> None:
    """网页只返回有限静态正文，不执行脚本或输出隐藏脚本内容。"""
    monkeypatch.setattr(client, 'fetch_public', lambda url: client.WebResponse(url, 'text/html',
                        ('<script>SECRET</script><p>' + '正文' * 4000 + '</p>').encode()))
    result = asyncio.run(client.read_webpage('https://example.com'))
    assert result['truncated'] and len(result['text']) == 6000
    assert 'SECRET' not in result['text']


@pytest.mark.parametrize('status,code', [(401, 'search_auth_failed'), (403, 'search_access_denied'),
                                       (429, 'search_rate_limited'), (500, 'search_provider_error')])
@pytest.mark.parametrize('transport_error', [False, True])
def test_bocha_errors_do_not_commit_interest(
    monkeypatch: pytest.MonkeyPatch, status: int, code: str, transport_error: bool,
) -> None:
    """HTTP 及业务错误不会泄漏正文或推进兴趣游标。

    Args:
        monkeypatch: 替换公网传输，禁止真实请求。
        status: 供应商错误码。
        code: 期望返回的安全错误码。
        transport_error: 是否模拟 HTTP 失败，而非 HTTP 200 的业务错误。
    """
    monkeypatch.setattr(client, 'fetch_bocha', bocha_fixture)
    def fetch(url: str, *args: object, **kwargs: object) -> client.WebResponse:
        if transport_error:
            raise client.PublicHttpError(status)
        return client.WebResponse(url, 'application/json', json.dumps({
            'code': status, 'msg': 'private-provider-detail', 'data': None,
        }).encode())
    monkeypatch.setattr(client, 'fetch_public', fetch)
    state = CompanionState(interests=[Interest(id='i', topic='游戏', source_run_id='r', evidence='我喜欢游戏')])
    result = asyncio.run(check_interest_updates(state, 'i', 'test-secret'))
    assert result['error'] == code
    assert 'private-provider-detail' not in json.dumps(result)
    assert state.interests[0].seen_urls == []
    assert state.interests[0].checked_at is None


def test_bocha_results_bounds_and_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """保留来源、采用摘要回退、限制数量与长度，并区分合法空结果。

    Args:
        monkeypatch: 替换博查响应。
    """
    monkeypatch.setattr(client, 'fetch_bocha', bocha_fixture)
    payload = {'code': 200, 'data': {'webPages': {'value': [
        {'name': '危险链接', 'url': 'javascript:alert(1)'},
        *[{'name': '标题' * 200, 'url': f'https://example.com/{n}', 'snippet': '摘要' * 400}
          for n in range(8)],
    ]}}}
    monkeypatch.setattr(client, 'fetch_public', lambda url, *a, **k:
                        client.WebResponse(url, 'application/json', json.dumps(payload).encode()))
    result = asyncio.run(client.search_web('中文', 'test-secret'))
    assert len(result['results']) == 5
    assert len(result['results'][0]['title']) == 200
    assert len(result['results'][0]['description']) == 600
    assert result['results'][0]['url'] == 'https://example.com/0'
    payload['data']['webPages']['value'] = []
    assert asyncio.run(client.search_web('中文', 'test-secret'))['results'] == []


@pytest.mark.parametrize('status', [301, 302, 307, 308])
def test_bocha_post_does_not_follow_redirect(monkeypatch: pytest.MonkeyPatch, status: int) -> None:
    """固定服务正确编码中文，且重定向不得转发 Key 或查询正文。

    Args:
        monkeypatch: 替换 HTTP 连接。
        status: 供应商返回的重定向状态。
    """
    sent = []
    actual_client = httpx.AsyncClient
    def handle(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(status, headers={'location': 'https://untrusted.test/'})
    def connection(**kwargs: object) -> httpx.AsyncClient:
        assert kwargs['trust_env'] is False and kwargs['follow_redirects'] is False
        return actual_client(transport=httpx.MockTransport(handle), **kwargs)
    monkeypatch.setattr(httpx, 'AsyncClient', connection)
    with pytest.raises(client.PublicHttpError):
        asyncio.run(client.fetch_bocha('中文搜索', 'test-key'))
    assert len(sent) == 1
    assert str(sent[0].url) == client.BOCHA_SEARCH_URL
    assert sent[0].method == 'POST'
    assert sent[0].headers['authorization'] == 'Bearer test-key'
    assert json.loads(sent[0].content) == {
        'query': '中文搜索', 'count': 5, 'summary': True, 'freshness': 'noLimit',
    }


def test_bocha_response_size_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """固定搜索端点也必须执行响应大小限制。

    Args:
        monkeypatch: 替换 HTTP 连接返回超限正文。
    """
    actual_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: actual_client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b'x' * (client.MAX_RESPONSE_BYTES + 1))),
        **kwargs))
    with pytest.raises(ValueError, match='搜索响应过大'):
        asyncio.run(client.fetch_bocha('中文搜索', 'test-key'))


def test_bocha_config_does_not_reuse_legacy_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """旧搜索或模型 Key 不会被误发给新供应商。

    Args:
        monkeypatch: 隔离环境变量与本地配置读取。
    """
    from src.tidebound import config
    monkeypatch.setattr(config, 'load_dotenv', lambda *args, **kwargs: None)
    monkeypatch.delenv('TIDEBOUND_BOCHA_API_KEY', raising=False)
    monkeypatch.setenv('TIDEBOUND_SEARCH_API_KEY', 'old-brave-secret')
    monkeypatch.setenv('TIDEBOUND_LLM_API_KEY', 'model-secret')
    assert config.AgentSettings.from_env().search_api_key.get_secret_value() == ''
    monkeypatch.setenv('TIDEBOUND_BOCHA_API_KEY', 'bocha-secret')
    assert config.AgentSettings.from_env().search_api_key.get_secret_value() == 'bocha-secret'


@pytest.mark.parametrize('payload', [[], {'code': 200, 'data': None},
    {'code': 200, 'data': {'webPages': {'value': 'bad'}}},
    {'code': 200, 'data': {'webPages': {'value': [None]}}}])
def test_bocha_invalid_response_preserves_interest(monkeypatch: pytest.MonkeyPatch, payload: object) -> None:
    """非法响应不能伪装成成功的无更新检查。

    Args:
        monkeypatch: 替换网络返回。
        payload: 格式不合法的供应商响应。
    """
    monkeypatch.setattr(client, 'fetch_bocha', bocha_fixture)
    monkeypatch.setattr(client, 'fetch_public', lambda url, *a, **k:
                        client.WebResponse(url, 'application/json', json.dumps(payload).encode()))
    state = CompanionState(interests=[Interest(id='i', topic='游戏', source_run_id='r', evidence='我喜欢游戏')])
    with pytest.raises(TypeError):
        asyncio.run(check_interest_updates(state, 'i', 'test-secret'))
    assert state.interests[0].checked_at is None
    assert state.interests[0].seen_urls == []


async def bocha_fixture(query: str, api_key: str) -> client.WebResponse:
    """通过各测试替换的同步 fixture 返回博查协议数据，不发起网络请求。

    Args:
        query: 适配器传入的搜索词。
        api_key: 测试凭据。

    Returns:
        当前测试构造的响应。
    """
    return client.fetch_public(client.BOCHA_SEARCH_URL, {'Authorization': f'Bearer {api_key}'})
