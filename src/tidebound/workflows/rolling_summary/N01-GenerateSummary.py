# ruff: noqa: N999 -- 沿用工作流顺序节点文件命名
"""根据本批资料生成尚未通过独立复核的摘要草稿。"""

from src.tidebound.config import AgentSettings
from src.tidebound.llm import ModelClient
from src.tidebound.runtime.types import Message
from src.tidebound.workflows.rolling_summary.model import request_content
from src.tidebound.workflows.rolling_summary.references import ReferencedContent


async def generate_draft(prompt: str, messages: list[Message], settings: AgentSettings,
                         model: ModelClient, step_number: int) -> ReferencedContent:
    """执行摘要生成节点，保留短引用供下一个节点独立复核。

    Args:
        prompt: 本批固定的摘要整理规则。
        messages: 已纳入预算的旧摘要、新轮次及证据资料。
        settings: 独立摘要模型与预算配置。
        model: 无工具权限的模型客户端。
        step_number: 本次生成的审计步骤编号。

    Returns:
        未发布且尚待复核的结构化草稿。

    Raises:
        AgentError: 请求超预算或响应不完整。
        ValueError: 响应结构或大小不合法。
        asyncio.CancelledError: 本次生成已取消。
    """
    return await request_content(prompt, messages, settings, model, step_number)
