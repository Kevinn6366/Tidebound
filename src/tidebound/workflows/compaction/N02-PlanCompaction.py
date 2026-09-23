# ruff: noqa: N999 -- 用户指定 N01-功能 的节点文件命名
"""规划节点：确定新增覆盖范围及摘要请求独立预算。"""

from src.tidebound.context.compaction import needs_compaction, plan_compaction
from src.tidebound.debug import TerminalDebug
from src.tidebound.prompting import load_prompt_bundles
from src.tidebound.workflows.compaction.types import CompactionInput, CompactionPlan, CompactionSource


def build_plan(inputs: CompactionInput, source: CompactionSource) -> CompactionPlan | None:
    """达到 90% 或手动触发后选择完整轮次前缀，并预留最多 15% 输入额度给摘要。

    Args:
        inputs: 工作流的预算与历史快照。
        source: 读取节点提供的有效摘要和上下文。

    Returns:
        压缩计划；未达到阈值时为空。

    Raises:
        AgentError: 目标预算不可达或压缩提示词无法加载。
    """
    if inputs.trigger == "automatic" and not needs_compaction(source.before.input_used, inputs.settings):
        return None
    budget = plan_compaction(inputs.system, inputs.records, inputs.current, inputs.tools,
                          source.previous, source.injection, inputs.settings)
    covered = len(source.previous.covered_run_ids) if source.previous else 0
    end, maximum = budget.end, budget.maximum
    TerminalDebug(inputs.settings.debug, "Compaction").write("N02-PlanCompaction",
        f"covered={end}, summary_max_bytes={maximum}, target_input={budget.target_input}, "
        f"fallback={budget.fallback}\n")
    prompt = load_prompt_bundles(inputs.settings.prompts_dir, ("context.compaction",))
    settings = inputs.settings.model_copy(update={"max_output_tokens": min(maximum, inputs.settings.max_output_tokens)})
    return CompactionPlan(source, end, inputs.records[covered:end], maximum, prompt, settings, budget.target_input, budget.fallback)
