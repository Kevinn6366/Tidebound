"""有界公网读取：每跳验证地址并直连已验证 IP，避免 DNS 重绑定。"""
import asyncio
import http.client
import ipaddress
import json
import socket
import ssl
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urlencode, urljoin, urlsplit

import httpx

MAX_RESPONSE_BYTES = 512_000
BOCHA_SEARCH_URL = "https://api.bocha.cn/v1/web-search"


class PublicHttpError(ValueError):
    """只携带状态码，不携带供应商正文或凭据。"""

    def __init__(self, status: int) -> None:
        self.status = status
        super().__init__(f"远程服务返回 HTTP {status}")


@dataclass
class WebResponse:
    url: str
    content_type: str
    body: bytes


def public_address(host: str, port: int) -> str:
    """解析主机并拒绝任何非公网候选地址。

    Args:
        host: 不含凭据的主机名。
        port: 已校验的 HTTP 或 HTTPS 标准端口。

    Returns:
        本次连接唯一允许使用的公网 IP。

    Raises:
        ValueError: DNS 指向本机、内网、保留或混合地址。
        OSError: DNS 解析失败。
    """
    addresses = [entry[4][0] for entry in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)]
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ValueError('禁止访问非公网地址')
    return addresses[0]


def fetch_public(url: str, headers: dict[str, str] | None = None) -> WebResponse:
    """有界读取公开网页，每次重定向重新检查目标且不转发凭据。

    Args:
        url: HTTP/HTTPS 公网地址，禁止用户信息及非标准端口。
        headers: 仅服务端配置的 API 请求头，重定向时清除。

    Returns:
        最终 URL、媒体类型和有大小限制的响应正文。

    Raises:
        ValueError: 非公网 URL、重定向过多、编码不支持或响应超限。
        PublicHttpError: 远程 HTTP 状态失败。
        OSError: 网络或 TLS 失败。
        HTTPException: HTTP 协议错误。
    """
    deadline = time.monotonic() + 25
    for hop in range(4):
        parsed = urlsplit(url)
        port = 443 if parsed.scheme == 'https' else 80
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username
                or parsed.password or parsed.port not in (None, port) or len(url) > 2048
                or any(ord(c) < 32 for c in url)):
            raise ValueError('不允许的网页地址')
        host = parsed.hostname.encode('idna').decode('ascii')
        address = public_address(host, port)
        connection = http.client.HTTPConnection(host, port, timeout=10)
        # 先固定 IP，再以原始域名做 TLS 校验；后续请求不会重新解析 DNS。
        sock = socket.create_connection((address, port), timeout=10)
        try:
            if parsed.scheme == 'https':
                sock = ssl.create_default_context().wrap_socket(sock, server_hostname=host)
            connection.sock = sock
            request_headers = {'User-Agent': 'Tidebound/0.0.3', 'Accept-Encoding': 'identity'}
            if hop == 0 and headers:
                request_headers.update(headers)
            connection.request('GET', (parsed.path or '/') + ('?' + parsed.query if parsed.query else ''),
                               headers=request_headers)
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader('Location')
                if not location:
                    raise ValueError('重定向没有目标')
                url = urljoin(url, location)
                continue
            if response.status != 200:
                raise PublicHttpError(response.status)
            if response.getheader('Content-Encoding', 'identity') != 'identity':
                raise ValueError('不支持压缩响应')
            chunks: list[bytes] = []
            size = 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('公网读取超时')
                sock.settimeout(min(10, remaining))
                chunk = response.read1(min(16384, MAX_RESPONSE_BYTES + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > MAX_RESPONSE_BYTES:
                    raise ValueError('网页响应过大')
            body = b''.join(chunks)
            return WebResponse(url, response.getheader('Content-Type', ''), body)
        finally:
            connection.close()
            sock.close()
    raise ValueError('重定向次数超限')


class PageText(HTMLParser):
    """提取静态可见文本，不执行脚本或加载子资源。"""

    def __init__(self) -> None:
        super().__init__()
        self.hidden = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ('script', 'style', 'noscript'):
            self.hidden += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in ('script', 'style', 'noscript'):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data: str) -> None:
        if not self.hidden and data.strip():
            self.parts.append(data.strip())


async def read_webpage(url: str) -> dict[str, object]:
    """读取有界静态网页文本，不把内容视为指令。

    Args:
        url: 模型请求访问的公网网页。

    Returns:
        来源 URL、正文片段和截断标记。

    Raises:
        ValueError: URL、响应大小或媒体类型不支持。
        OSError: 网络失败。
    """
    response = await asyncio.to_thread(fetch_public, url)
    if not any(kind in response.content_type for kind in ('text/html', 'text/plain', 'application/xhtml+xml')):
        raise ValueError('只支持文本网页')
    text = response.body.decode('utf-8', errors='replace')
    if 'html' in response.content_type:
        parser = PageText()
        parser.feed(text)
        text = '\n'.join(parser.parts)
    return {'url': response.url, 'text': text[:6000], 'truncated': len(text) > 6000, 'untrusted': True}


async def fetch_json(url: str, headers: dict[str, str] | None = None) -> dict[str, object]:
    """通过同一公网限制读取供应商 JSON。

    Args:
        url: 代码构造的供应商请求 URL。
        headers: 后端凭据，禁止来自模型参数。

    Returns:
        JSON 对象。

    Raises:
        ValueError: 响应格式不是 JSON 对象。
        OSError: 网络失败。
    """
    response = await asyncio.to_thread(fetch_public, url, headers)
    result = json.loads(response.body)
    if not isinstance(result, dict):
        raise TypeError('响应不是对象')
    return result


async def fetch_bocha(query: str, api_key: str) -> WebResponse:
    """有界调用代码固定的博查 HTTPS 服务，兼容代理的虚拟 DNS。

    模型只能提供搜索词，不能控制请求地址；与任意网页读取不同，不按
    DNS 返回 IP 拒绝该固定服务。保持证书校验，禁止重定向和环境代理。

    Args:
        query: 发送到博查的公开搜索词。
        api_key: 后端保存的博查凭据。

    Returns:
        大小限制内的供应商响应。

    Raises:
        PublicHttpError: HTTP 状态非 200，包括重定向。
        ValueError: 响应正文过大。
        TimeoutError: 整次调用超过 25 秒。
        httpx.HTTPError: 网络或 TLS 失败。
    """
    async with asyncio.timeout(25), httpx.AsyncClient(
        timeout=10, trust_env=False, follow_redirects=False,
    ) as connection, connection.stream('POST', BOCHA_SEARCH_URL,
        headers={'Authorization': f'Bearer {api_key}'},
        json={'query': query, 'count': 5, 'summary': True, 'freshness': 'noLimit'},
    ) as response:
        if response.status_code != 200:
            raise PublicHttpError(response.status_code)
        body = bytearray()
        async for chunk in response.aiter_bytes(chunk_size=16384):
            body.extend(chunk)
            if len(body) > MAX_RESPONSE_BYTES:
                raise ValueError('搜索响应过大')
        return WebResponse(BOCHA_SEARCH_URL, response.headers.get('content-type', ''), bytes(body))


def search_failure(status: object) -> dict[str, object]:
    """将供应商状态转换为有限的安全错误，不回传供应商原文。

    Args:
        status: HTTP 状态或博查业务错误码。

    Returns:
        供模型判断失败的错误码与简短说明。
    """
    errors = {
        '401': ('search_auth_failed', '搜索服务认证失败，请检查博查 API Key。'),
        '403': ('search_access_denied', '搜索服务拒绝访问，请检查博查额度与权限。'),
        '429': ('search_rate_limited', '搜索服务请求过于频繁，请稍后再试。'),
    }
    code, message = errors.get(str(status), ('search_provider_error', '搜索服务暂时不可用。'))
    return {'error': code, 'message': message}


async def search_web(query: str, api_key: str) -> dict[str, object]:
    """调用博查 Web Search，将结果规范化为现有工具输出。

    Args:
        query: 用户话题相关的查询词，通过 UTF-8 JSON 发送。
        api_key: 后端博查凭据，不进入结果或模型上下文。

    Returns:
        最多五条标题、链接及摘要；配置或供应商失败返回安全错误。

    Raises:
        ValueError: 供应商正文超限或不是合法 JSON。
        TypeError: 供应商响应字段类型非法。
        httpx.HTTPError: 网络或 TLS 失败。
        TimeoutError: 搜索超过时限。
    """
    if not api_key.strip():
        return {'error': 'search_not_configured', 'message': '后端尚未配置博查搜索服务。'}
    try:
        response = await fetch_bocha(query, api_key)
    except PublicHttpError as error:
        return search_failure(error.status)
    payload = json.loads(response.body)
    if not isinstance(payload, dict):
        raise TypeError('博查响应不是对象')
    if payload.get('code') != 200:
        return search_failure(payload.get('code'))
    data = payload.get('data')
    if not isinstance(data, dict):
        raise TypeError('博查搜索数据非法')
    web = data.get('webPages')
    if web is None:
        web = {}
    if not isinstance(web, dict) or not isinstance(web.get('value', []), list):
        raise TypeError('博查网页结果非法')
    results: list[dict[str, str]] = []
    for row in web.get('value', []):
        if not isinstance(row, dict):
            raise TypeError('博查网页条目非法')
        url = row.get('url')
        if not isinstance(url, str) or len(url) > 2048:
            continue
        try:
            parsed = urlsplit(url)
            valid = parsed.scheme in ('http', 'https') and parsed.hostname and not parsed.username and not parsed.password
        except ValueError:
            valid = False
        if not valid or any(ord(c) < 32 for c in url):
            continue
        title = row.get('name')
        description = row.get('summary') or row.get('snippet') or ''
        if not isinstance(title, str) or not isinstance(description, str):
            raise TypeError('博查网页标题或摘要非法')
        results.append({'title': title[:200], 'url': url, 'description': description[:600]})
        if len(results) == 5:
            break
    return {'results': results, 'untrusted': True}


async def get_weather(location: str, latitude: float | None, longitude: float | None) -> dict[str, object]:
    """查询明确地点的天气，同名地点先返回候选供主 Agent 澄清。

    Args:
        location: 用户明确提供的地点名称。
        latitude: 已确认地点的纬度，可从候选读取。
        longitude: 已确认地点的经度，须与纬度同时提供。

    Returns:
        地点候选或含单位、时区和来源的三天天气。

    Raises:
        ValueError: 经纬度不完整或供应商数据非法。
        OSError: 网络失败。
    """
    if (latitude is None) != (longitude is None):
        raise ValueError('经纬度必须一起提供')
    if latitude is None:
        data = await fetch_json('https://geocoding-api.open-meteo.com/v1/search?' +
                                urlencode({'name': location, 'count': 5, 'language': 'zh'}))
        results = data.get('results', [])
        if not isinstance(results, list):
            raise ValueError('地点结果非法')
        candidates = [{key: row.get(key) for key in ('name', 'country', 'admin1', 'latitude', 'longitude')}
                      for row in results[:5] if isinstance(row, dict)]
        if len(candidates) != 1:
            return {'locations': candidates, 'requires_location_confirmation': True, 'source': 'Open-Meteo'}
        latitude, longitude = candidates[0]['latitude'], candidates[0]['longitude']
    url = 'https://api.open-meteo.com/v1/forecast?' + urlencode({
        'latitude': latitude, 'longitude': longitude, 'current': 'temperature_2m,weather_code',
        'daily': 'temperature_2m_max,temperature_2m_min,precipitation_probability_max',
        'forecast_days': 3, 'timezone': 'auto'})
    data = await fetch_json(url)
    return {'location': location, 'source': url,
            **{key: data.get(key) for key in ('latitude', 'longitude', 'timezone', 'current', 'current_units',
                                             'daily', 'daily_units')}}
