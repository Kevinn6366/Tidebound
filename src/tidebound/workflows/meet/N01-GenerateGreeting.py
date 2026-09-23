# ruff: noqa: N999 -- 沿用工作流顺序节点文件命名
"""让问候模型自主选择时间工具，只将最终正文交给验证节点。"""

import asyncio
from collections.abc import Awaitable, Callable

from src.tidebound.config import AgentSettings
from src.tidebound.context.compaction import PreparedContext
from src.tidebound.llm import ModelClient
from src.tidebound.runtime.agent_loop import agent_loop
from src.tidebound.runtime.types import ContextUsage, Message, ModelReply
from src.tidebound.storage.model_requests import request_purpose
from src.tidebound.tools.registry import create_tools


async def generate_greeting(
    system: str, event: Message, model: ModelClient, injection: str,
    settings: AgentSettings, stop: asyncio.Event,
    prepare_context: Callable[[str, list[Message], list[dict[str, object]]], Awaitable[PreparedContext]],
    on_context: Callable[[ContextUsage], None],
) -> ModelReply:
    """复用受控模型循环，由模型自主提出时间查询，再生成完整问候。

    Args:
        system: 本轮固定的角色、安全及世界观内容。
        event: 见面事件与历史时间，不包含当前时间。
        model: 欢迎专用模型客户端。
        injection: 本轮欢迎规则，参与预算及每次请求审计。
        settings: 欢迎模型的预算、调用上限和工具时区配置。
        stop: runtime 提供的停止信号。
        prepare_context: 加载有效历史和摘要并检查每次请求预算。
        on_context: 记录每次请求的实际预算用量。

    Returns:
        待验证的最终模型回复；事件及工具链只进入请求审计。

    Raises:
        AgentError: 停止、模型或工具协议失败、预算或调用次数超限。
        OSError: 提示词或审计记录读写失败。
    """
    purpose = request_purpose.set("chat.meet")
    try:
        messages = await agent_loop(
            f"{system}\n\n{injection}", [], [event], model, settings, stop,
            create_tools(settings.timezone), on_context, prepare_context,
            base_injection=injection,
        )
        return ModelReply(message=messages[-1], finish_reason="stop")
    finally:
        request_purpose.reset(purpose)
