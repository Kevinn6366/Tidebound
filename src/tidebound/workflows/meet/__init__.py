"""生成并校验欢迎语，工具选择归模型，提交资格由 runtime 检查。"""

import asyncio
from collections.abc import Awaitable, Callable
from importlib import import_module

from src.tidebound.config import AgentSettings
from src.tidebound.context.compaction import PreparedContext
from src.tidebound.llm import ModelClient
from src.tidebound.runtime.types import ContextUsage, Message

generate_greeting = import_module(f"{__name__}.N01-GenerateGreeting").generate_greeting
validate_greeting = import_module(f"{__name__}.N02-ValidateGreeting").validate_greeting


async def run_meet(
    system: str, event: Message, model: ModelClient, injection: str,
    settings: AgentSettings, stop: asyncio.Event,
    prepare_context: Callable[[str, list[Message], list[dict[str, object]]], Awaitable[PreparedContext]],
    on_context: Callable[[ContextUsage], None],
) -> Message:
    """执行欢迎工作流，允许模型自主查询时间，不自行修改会话状态。

    Args:
        system: 本轮固定的角色、安全及世界观内容。
        event: 见面事件资料，不包含后端预先读取的当前时间。
        model: 本次欢迎使用的模型客户端。
        injection: 临时欢迎提示词，用于生成及审计。
        settings: 本轮模型预算、调用上限及工具时区。
        stop: runtime 的停止信号，设置后取消调用并禁止提交。
        prepare_context: 每次调用的有效上下文组装与预算检查入口。
        on_context: 实际上下文用量的展示回调。

    Returns:
        等待 runtime 原子提交的单条问候。

    Raises:
        AgentError: 停止、模型失败、调用超限或问候非法。
        OSError: 请求审计保存失败。
    """
    reply = await generate_greeting(system, event, model, injection, settings, stop, prepare_context, on_context)
    return validate_greeting(reply)
