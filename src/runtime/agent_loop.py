"""参考 Pi 的模型—工具—模型循环，保持与 HTTP 和存储无关。"""

import asyncio

from src.config import AgentSettings
from src.context.budget import select_messages
from src.debug import TerminalDebug
from src.errors import AgentError
from src.llm import ModelClient
from src.runtime.types import Message
from src.tools.registry import ToolRegistry


async def agent_loop(system: str, history: list[list[Message]], current: list[Message],
                     model: ModelClient, settings: AgentSettings, stop: asyncio.Event, registry: ToolRegistry) -> list[Message]:
    """执行有限模型循环，记录中间消息但仅返回完整轮次。

    Args:
        system: 此 Run 开始时加载的角色内容。
        history: 有效已提交轮次。
        current: 本轮消息缓冲，供会话层保留失败或停止记录。
        model: 可替换的模型请求边界。
        settings: 模型调用上限、预算和工具时区。
        stop: 会话层控制的停止信号。
        registry: 已授权的工具注册表，循环不依赖具体工具。

    Returns:
        包含用户消息、工具链和最终回复的本轮消息。

    Raises:
        AgentError: 停止、模型异常、协议错误、预算或循环次数超限。
    """
    tools = registry.definitions()
    debug = TerminalDebug(settings.debug, "Agent")
    for step in range(settings.max_model_calls):
        debug.write("模型调用", f"第 {step + 1}/{settings.max_model_calls} 次\n")
        if stop.is_set():
            raise AgentError("run_stopped", "本次回复已停止。")
        messages = select_messages(system, history, current, tools, settings)
        model_task = asyncio.create_task(model.complete(system, messages, tools))
        stop_task = asyncio.create_task(stop.wait())
        try:
            await asyncio.wait({model_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
            if stop.is_set():
                raise AgentError("run_stopped", "本次回复已停止。")
            reply = await model_task
        finally:
            for task in (model_task, stop_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(model_task, stop_task, return_exceptions=True)
        if reply.finish_reason not in ("stop", "tool_calls"):
            raise AgentError("model_incomplete", "模型回复未完整结束，本轮未保存。", 502)
        message = reply.message
        current.append(message)
        if not message.tool_calls:
            if reply.finish_reason != "stop" or not message.content.strip():
                raise AgentError("empty_model_response", "模型没有返回完整回复。", 502)
            return current
        if len(message.tool_calls) > 8 or len({c.id for c in message.tool_calls}) != len(message.tool_calls):
            raise AgentError("invalid_tool_calls", "模型工具调用数量或标识非法。", 502)
        for call in message.tool_calls:
            if stop.is_set():
                raise AgentError("run_stopped", "本次回复已停止。")
            debug.write("工具执行", f"{call.name}\n")
            result = registry.invoke(call)
            current.append(result)
            debug.write("工具结果", result.content + "\n")
    raise AgentError("model_call_limit", "本次执行已达到模型调用上限，未生成完整回复。", 502)
