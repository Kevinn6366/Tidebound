"""按固定顺序生成并校验欢迎语，提交资格由 runtime 检查。"""

import asyncio
from importlib import import_module

from src.tidebound.context.compaction import PreparedContext
from src.tidebound.errors import AgentError
from src.tidebound.llm import ModelClient
from src.tidebound.runtime.types import Message

generate_greeting = import_module(f"{__name__}.N01-GenerateGreeting").generate_greeting
validate_greeting = import_module(f"{__name__}.N02-ValidateGreeting").validate_greeting


async def run_meet(context: PreparedContext, model: ModelClient, injection: str, stop: asyncio.Event) -> Message:
    """执行一次欢迎工作流，不自行修改会话状态。

    Args:
        context: 已组装并检查预算的有效上下文。
        model: 本次欢迎使用的模型客户端。
        injection: 临时欢迎提示词，用于审计。
        stop: runtime 的停止信号，设置后取消调用并禁止提交。

    Returns:
        等待 runtime 原子提交的单条问候。

    Raises:
        AgentError: 模型失败或问候非法。
        OSError: 请求审计保存失败。
    """
    if stop.is_set():
        raise AgentError("run_stopped", "本次问候已停止。")
    generation = asyncio.create_task(generate_greeting(context, model, injection))
    stopping = asyncio.create_task(stop.wait())
    try:
        await asyncio.wait({generation, stopping}, return_when=asyncio.FIRST_COMPLETED)
        if stop.is_set():
            raise AgentError("run_stopped", "本次问候已停止。")
        return validate_greeting(await generation)
    finally:
        for task in (generation, stopping):
            if not task.done():
                task.cancel()
        await asyncio.gather(generation, stopping, return_exceptions=True)
