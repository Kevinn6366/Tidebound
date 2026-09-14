"""仅供端到端测试的本地 Chat Completions 协议服务，不代表真实模型。"""
import asyncio
import json

from fastapi import FastAPI, Request

app = FastAPI()


@app.get('/health')
def health() -> dict[str, bool]:
    return {'ok': True}


@app.post('/v1/chat/completions')
async def complete(request: Request) -> dict[str, object]:
    """按最新用户输入返回工具调用或明确标识的测试回复。

    Args:
        request: 由真实后端 HTTP 客户端发来的协议请求。

    Returns:
        符合工具回填协议的最小响应。
    """
    payload = await request.json()
    messages = payload['messages']
    current_user = next(m['content'] for m in reversed(messages) if m['role'] == 'user')
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
    return {'choices': [{'message': {'role': 'assistant', 'content': '协议测试：已收到。'}, 'finish_reason': 'stop'}]}
