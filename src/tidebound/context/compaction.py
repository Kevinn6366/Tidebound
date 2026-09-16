"""滚动摘要的预算与材料组织，所有计量沿用保守 UTF-8 字节口径。"""

import json
from dataclasses import dataclass

from src.tidebound.config import AgentSettings
from src.tidebound.context.budget import FORMAT_MARGIN, measure_input
from src.tidebound.errors import AgentError
from src.tidebound.runtime.types import Message, RunRecord
from src.tidebound.storage.summaries import ContextSummary

TRIGGER_RATIO = 0.90
TARGET_RATIO = 0.70
SUMMARY_RATIO = 0.15
RECENT_TURNS = 5
FALLBACK_RATIO = 0.98
SUMMARY_FORMAT_MARGIN = 64
MIN_SUMMARY_BYTES = 256


@dataclass
class CompactionBudget:
    end: int
    maximum: int
    target_input: int
    fallback: bool


@dataclass
class PreparedContext:
    system: str
    messages: list[Message]
    input_used: int


def assemble_context(system: str, records: list[RunRecord], current: list[Message],
                     tools: list[dict[str, object]], summary: ContextSummary | None,
                     injection: str) -> PreparedContext:
    """用摘要替换精确覆盖的历史前缀，其余完整轮次不裁剪。

    Args:
        system: 角色及本次工具临时规则。
        records: 有效已提交历史。
        current: 本轮原始输入与工具链。
        tools: 本次工具声明。
        summary: 已验证来源的历史摘要。
        injection: 静态摘要使用规则。

    Returns:
        组装后的系统内容、消息及输入估算。
    """
    messages: list[Message] = []
    covered = 0
    if summary is not None:
        system = f"{system}\n\n{injection}"
        messages.append(Message(role="user", content=json.dumps(
            {"context_summary": summary.content}, ensure_ascii=False)))
        covered = len(summary.covered_run_ids)
    messages.extend(message for record in records[covered:] for message in record.messages)
    messages.extend(current)
    return PreparedContext(system, messages, measure_input(system, messages, tools))


def input_budget(settings: AgentSettings) -> int:
    return settings.context_limit - settings.max_output_tokens - FORMAT_MARGIN


def needs_compaction(input_used: int, settings: AgentSettings) -> bool:
    return input_used + settings.max_output_tokens + FORMAT_MARGIN >= settings.context_limit * TRIGGER_RATIO


def plan_compaction(system: str, records: list[RunRecord], current: list[Message],
                    tools: list[dict[str, object]], summary: ContextSummary | None,
                    injection: str, settings: AgentSettings) -> CompactionBudget:
    """选择需要摘要覆盖的历史前缀，始终保留最近五轮完整原文，并为更早历史规划摘要。

    Args:
        system: 本次固定提示词和临时规则。
        records: 有效已提交历史。
        current: 不参与压缩的当前轮次。
        tools: 主模型工具声明。
        summary: 已有摘要。
        injection: 摘要使用规则。
        settings: 当前预算配置快照。

    Returns:
        新摘要覆盖范围、长度上限与本次可达的输入目标。

    Raises:
        AgentError: 必需内容过大、没有可压缩历史或目标预算无法满足。
    """
    reserved = settings.max_output_tokens + FORMAT_MARGIN
    target = int(settings.context_limit * TARGET_RATIO) - reserved
    maximum = int(input_budget(settings) * SUMMARY_RATIO)
    covered = len(summary.covered_run_ids) if summary else 0
    end = len(records) - RECENT_TURNS
    if end <= covered:
        raise AgentError("context_budget_exceeded", "没有可压缩的更早历史；最近五轮完整对话需要保留。", 413)
    placeholder = ContextSummary(timeline_id=records[0].timeline_id,
        covered_run_ids=[item.run_id for item in records[:end]], content="",
        prompt_name="", prompt_hash="", model="", input_before=0, input_after=0, summary_max_bytes=maximum)
    floor = assemble_context(system, records, current, tools, placeholder, injection).input_used
    fallback = floor + MIN_SUMMARY_BYTES + SUMMARY_FORMAT_MARGIN > target
    if fallback:
        # 固定提示词与输出预留不能压缩，70% 是优化目标，不能成为禁止生成摘要的门槛。
        target = int(settings.context_limit * FALLBACK_RATIO) - reserved
    maximum = min(maximum, target - floor - SUMMARY_FORMAT_MARGIN)
    if maximum < MIN_SUMMARY_BYTES:
        raise AgentError("context_budget_exceeded",
            "固定提示词、最近五轮、回复预留和当前输入占用过高，已无足够摘要空间，请调大上下文预算。", 413)
    # 最近五轮与当前消息属于必需原文，预算不足时不能扩大摘要覆盖范围。
    return CompactionBudget(end, maximum, target, fallback)
