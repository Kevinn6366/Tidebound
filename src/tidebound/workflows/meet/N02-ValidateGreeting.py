# ruff: noqa: N999 -- 沿用工作流顺序节点文件命名
"""验证问候完整结束，拒绝空输出、工具调用和超长内容。"""

from src.tidebound.errors import AgentError
from src.tidebound.runtime.types import Message, ModelReply

MAX_GREETING_CHARACTERS = 120


def validate_greeting(reply: ModelReply) -> Message:
    """将合法输出转换为唯一可提交的角色消息。

    Args:
        reply: 欢迎模型的完整返回，不能把截断结果当成成功。

    Returns:
        不含内部推理或工具协议的角色正文。

    Raises:
        AgentError: 输出为空、超长、非角色正文或未正常结束。
    """
    content = reply.message.content.strip()
    if (reply.finish_reason != "stop" or reply.message.role != "assistant"
            or reply.message.tool_calls or not content or len(content) > MAX_GREETING_CHARACTERS):
        raise AgentError("invalid_greeting", "问候未完整生成，可重试或直接开始聊天。", 502)
    return Message(role="assistant", content=content)
