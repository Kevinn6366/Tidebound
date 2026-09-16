# ruff: noqa: N999 -- 用户指定 N01-功能 的节点文件命名
"""校验节点：验证完整请求降到 70% 以内，并建立摘要来源记录。"""

import hashlib

from src.tidebound.context.compaction import assemble_context
from src.tidebound.errors import AgentError
from src.tidebound.storage.summaries import ContextSummary
from src.tidebound.workflows.compaction.types import CompactionInput, CompactionPlan


def validate_summary(inputs: CompactionInput, plan: CompactionPlan, content: str) -> ContextSummary:
    """检查摘要长度及压缩后请求预算，不声称程序可以验证语义无损。

    Args:
        inputs: 主请求需要保留的材料和配置。
        plan: 已执行的压缩范围与提示词快照。
        content: 生成节点返回的完整摘要。

    Returns:
        可提交的候选摘要及来源、预算审计信息。

    Raises:
        AgentError: 摘要为空、超长或压缩后未达到目标。
    """
    if not content.strip() or len(content.encode("utf-8")) > plan.maximum:
        raise AgentError("invalid_compaction", "摘要为空或超出长度上限，保留原摘要。", 502)
    candidate = ContextSummary(timeline_id=inputs.timeline,
        covered_run_ids=[item.run_id for item in inputs.records[:plan.end]], content=content,
        parent_id=plan.source.previous.summary_id if plan.source.previous else None,
        prompt_name=plan.prompt.name, prompt_hash=hashlib.sha256(plan.prompt.content.encode()).hexdigest(),
        model=inputs.settings.model, input_before=plan.source.before.input_used, input_after=0,
        summary_max_bytes=plan.maximum, target_input=plan.target_input, target_fallback=plan.fallback)
    after = assemble_context(inputs.system, inputs.records, inputs.current, inputs.tools,
                             candidate, plan.source.injection)
    candidate.input_after = after.input_used
    if after.input_used > plan.target_input or after.input_used >= plan.source.before.input_used:
        raise AgentError("compaction_target_exceeded", "摘要未达到目标预算，保留原摘要。", 502)
    return candidate
