"""首版按完整轮次选择最近历史；不实现分项配额或摘要。"""

import json

from src.tidebound.config import AgentSettings
from src.tidebound.errors import AgentError
from src.tidebound.llm import wire_messages
from src.tidebound.runtime.types import ContextUsage, Message

FORMAT_MARGIN = 1024


def select_messages(system: str, history: list[list[Message]], current: list[Message],
                    tools: list[dict[str, object]], settings: AgentSettings) -> list[Message]:
    """用保守字节预算保留当前执行与能容纳的最近完整轮次。

    Args:
        system: 本轮角色提示词。
        history: 按时间排序的已提交轮次。
        current: 不允许静默删除的本次执行消息。
        tools: 请求内工具定义。
        settings: 有效上限及输出预留。

    Returns:
        按原时间顺序排列的上下文消息，不修改输入历史。

    Raises:
        AgentError: 必需材料已超出保守预算。
    """
    budget = settings.context_limit - settings.max_output_tokens - FORMAT_MARGIN

    def fits(messages: list[Message]) -> bool:
        return measure_input(system, messages, tools) <= budget

    selected = list(current)
    if not fits(selected):
        raise AgentError("context_budget_exceeded", "本轮内容超出上下文预算，请缩短输入或调整服务端配置。", 413)
    for turn in reversed(history):
        candidate = [*turn, *selected]
        if not fits(candidate):
            break
        selected = candidate
    return selected


def measure_input(system: str, messages: list[Message], tools: list[dict[str, object]]) -> int:
    """按与上下文选取完全相同的 JSON 字节口径计算输入大小。

    Args:
        system: 本次角色与一次性规则。
        messages: 实际选中的历史和本轮消息。
        tools: 本次工具声明。

    Returns:
        JSON UTF-8 字节数，不是供应商精确 token 统计。
    """
    payload = {"messages": wire_messages(system, messages), "tools": tools}
    return len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def context_usage(settings: AgentSettings, input_used: int | None = None) -> ContextUsage:
    """构造用于前端展示的预算明细。

    Args:
        settings: 当前执行的上下文与输出预留配置。
        input_used: 最近实际模型请求的输入估算量，未请求时为空。

    Returns:
        总预算、输入估算、输出预留和格式余量。
    """
    return ContextUsage(total=settings.context_limit, input_used=input_used,
                        output_reserved=settings.max_output_tokens, format_margin=FORMAT_MARGIN)
