# ruff: noqa: N999 -- 沿用工作流顺序节点文件命名
"""一次无工具的角色问候调用，不把事件资料提交为用户消息。"""

from src.tidebound.context.compaction import PreparedContext
from src.tidebound.llm import ModelClient
from src.tidebound.runtime.types import ModelReply
from src.tidebound.storage.model_requests import request_injection, request_purpose, request_step


async def generate_greeting(context: PreparedContext, model: ModelClient, injection: str) -> ModelReply:
    """使用已核算预算的角色上下文生成问候并关联审计。

    Args:
        context: 包含角色、安全、欢迎规则及有效历史的模型输入。
        model: 欢迎专用模型，不允许调用工具。
        injection: 本次临时欢迎规则，供 Console 检查。

    Returns:
        待验证的完整模型响应。

    Raises:
        AgentError: 模型调用或响应协议失败。
        OSError: 审计记录无法保存。
    """
    purpose = request_purpose.set("chat.meet")
    step = request_step.set(1)
    rules = request_injection.set(injection)
    try:
        return await model.complete(context.system, context.messages, [])
    finally:
        request_purpose.reset(purpose)
        request_step.reset(step)
        request_injection.reset(rules)
