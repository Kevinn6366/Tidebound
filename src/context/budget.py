"""首版按完整轮次选择最近历史；不实现分项配额或摘要。"""

import json

from src.config import AgentSettings
from src.errors import AgentError
from src.llm import wire_messages
from src.runtime.types import Message


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
    budget = settings.context_limit - settings.max_output_tokens - 1024

    def fits(messages: list[Message]) -> bool:
        payload = {"messages": wire_messages(system, messages), "tools": tools}
        return len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) <= budget

    selected = list(current)
    if not fits(selected):
        raise AgentError("context_budget_exceeded", "本轮内容超出上下文预算，请缩短输入或调整服务端配置。", 413)
    for turn in reversed(history):
        candidate = [*turn, *selected]
        if not fits(candidate):
            break
        selected = candidate
    return selected
