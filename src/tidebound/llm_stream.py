"""解析 Chat Completions SSE，保留思考与分片工具参数。"""
from collections.abc import AsyncIterator

import httpx
from pydantic import BaseModel, Field

from src.tidebound.debug import TerminalDebug
from src.tidebound.runtime.preview import publish_preview
from src.tidebound.runtime.types import Message, ModelReply, ToolCall


class FunctionDelta(BaseModel):
    name: str | None = None
    arguments: str | None = None


class CallDelta(BaseModel):
    index: int = Field(ge=0, le=7)
    id: str | None = None
    type: str | None = None
    function: FunctionDelta = Field(default_factory=FunctionDelta)


class Delta(BaseModel):
    role: str | None = None
    content: str | None = None
    reasoning_content: str | None = None
    tool_calls: list[CallDelta] | None = None


class Choice(BaseModel):
    index: int = 0
    delta: Delta
    finish_reason: str | None = None


class Chunk(BaseModel):
    choices: list[Choice] = Field(default_factory=list)
    error: object | None = None


async def event_data(response: httpx.Response) -> AsyncIterator[str]:
    """按 SSE 空行边界读取 data，忽略注释和事件元数据。

    Args:
        response: 已检查 HTTP 状态的流式响应。

    Yields:
        一个事件中合并后的 data 字符串。
    """
    parts: list[str] = []
    async for line in response.aiter_lines():
        if not line:
            if parts:
                yield "\n".join(parts)
                parts = []
        elif line.startswith("data:"):
            parts.append(line[5:].removeprefix(" "))
    if parts:
        yield "\n".join(parts)


async def read_stream(response: httpx.Response, debug: TerminalDebug) -> ModelReply:
    """合并增量消息，流中断或协议错误时不返回完整回复。

    Args:
        response: Chat Completions SSE 响应。
        debug: 当前请求的终端输出器。

    Returns:
        含思考内容、正文和完整工具参数的模型消息。

    Raises:
        ValueError: 缺少完成标记、错误事件或不支持的字段。
    """
    message = Message(role="assistant")
    calls: dict[int, dict[str, str]] = {}
    finish: str | None = None
    done = False
    async for data in event_data(response):
        if data == "[DONE]":
            done = True
            break
        chunk = Chunk.model_validate_json(data)
        if chunk.error is not None:
            raise ValueError("stream error")
        if not chunk.choices:
            continue  # 部分服务单独返回 usage。
        if len(chunk.choices) != 1 or chunk.choices[0].index != 0 or finish is not None:
            raise ValueError("unexpected stream choice")
        choice = chunk.choices[0]
        delta = choice.delta
        if delta.role not in (None, "assistant"):
            raise ValueError("unexpected role")
        if delta.reasoning_content:
            message.reasoning_content = (message.reasoning_content or "") + delta.reasoning_content
            debug.write("思考", delta.reasoning_content)
        if delta.content:
            message.content += delta.content
            debug.write("回复", delta.content)
        if delta.tool_calls:
            publish_preview("")
        elif delta.content and not calls:
            publish_preview(message.content)
        for part in delta.tool_calls or []:
            if part.type not in (None, "function"):
                raise ValueError("unexpected tool type")
            call = calls.setdefault(part.index, {"id": "", "name": "", "arguments": ""})
            call["id"] += part.id or ""
            call["name"] += part.function.name or ""
            call["arguments"] += part.function.arguments or ""
        finish = choice.finish_reason
    if not done or not finish:
        raise ValueError("stream ended without completion")
    message.tool_calls = [ToolCall.model_validate(calls[i]) for i in sorted(calls)]
    debug.write("结束", f"finish_reason={finish}\n")
    return ModelReply(message=message, finish_reason=finish)
