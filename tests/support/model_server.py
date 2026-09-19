"""仅供端到端测试的本地 Chat Completions 协议服务，不代表真实模型。"""
import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

app = FastAPI()


@app.get('/health')
def health() -> dict[str, bool]:
    return {'ok': True}


@app.post('/v1/chat/completions', response_model=None)
async def complete(request: Request) -> JSONResponse | StreamingResponse:
    """返回受控的分片响应，支持浏览器验证完成前已显示文字。

    Args:
        request: 模型适配器的真实 HTTP 请求。

    Returns:
        按 stream 参数返回 JSON 或逐字 SSE。
    """
    payload = await request.json()
    reply = await build_reply(payload)
    if not payload.get('stream'):
        return JSONResponse(reply)

    async def events() -> AsyncIterator[str]:
        """把受控回复分成正文或工具事件。

        Yields:
            含标准结束标记的 SSE 分片。
        """
        choice = reply['choices'][0]
        message = choice['message']
        if message.get('tool_calls'):
            message['tool_calls'][0]['index'] = 0
            yield 'data: ' + json.dumps({'choices': [{'index': 0, 'delta': message, 'finish_reason': None}]}) + '\n\n'
        else:
            for character in message['content']:
                yield 'data: ' + json.dumps({'choices': [{'index': 0, 'delta': {'content': character}, 'finish_reason': None}]}) + '\n\n'
                await asyncio.sleep(0.04)
        yield 'data: ' + json.dumps({'choices': [{'index': 0, 'delta': {}, 'finish_reason': choice['finish_reason']}]}) + '\n\n'
        yield 'data: [DONE]\n\n'

    return StreamingResponse(events(), media_type='text/event-stream')


async def build_reply(payload: dict[str, object]) -> dict[str, object]:
    """按用户问题生成协议测试回复，不代表真实模型质量。

    Args:
        payload: 模型请求正文。

    Returns:
        含工具调用或最终正文的 Chat Completions 响应。
    """
    messages = payload['messages']
    current_user = next(m['content'] for m in reversed(messages) if m['role'] == 'user')
    if '"event": "first_meet"' in current_user or '"event": "return_meet"' in current_user:
        await asyncio.sleep(2)
        return {'choices': [{'message': {'role': 'assistant', 'content': '你来啦，今天也一起聊些有趣的事情吧。'}, 'finish_reason': 'stop'}]}
    if '等待测试' in current_user:
        await asyncio.sleep(5)
    if messages[-1]['role'] == 'tool':
        result = json.loads(messages[-1]['content'])
        content = '协议测试：' + (result.get('datetime') or result.get('error', '工具已返回'))
        return {'choices': [{'message': {'role': 'assistant', 'content': content}, 'finish_reason': 'stop'}]}
    if '时间' in current_user or '几点' in current_user:
        return {'choices': [{'message': {'role': 'assistant', 'content': None, 'tool_calls': [
            {'id': 'test-time', 'type': 'function', 'function': {'name': 'get_current_time', 'arguments': '{}'}}
        ]}, 'finish_reason': 'tool_calls'}]}
    content = '协议测试：' + ('正在逐字返回模型生成的内容。' * 4 if '流式测试' in current_user else '已收到。')
    return {'choices': [{'message': {'role': 'assistant', 'content': content}, 'finish_reason': 'stop'}]}
