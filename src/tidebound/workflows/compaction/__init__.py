"""上下文压缩工作流：读取 → 规划 → 生成 → 校验 → 提交。"""

import logging
from importlib import import_module

from src.tidebound.llm import ChatCompletionsClient, ModelClient
from src.tidebound.storage.runs import RunStore
from src.tidebound.storage.summaries import ContextSummary, SummaryStore
from src.tidebound.workflows.compaction.types import CompactionInput, CompactionPlan, CompactionSource

# 用户要求节点文件采用 N01-功能 命名；import_module 支持带连字符的模块名。
N01 = import_module(".N01-ReadValidHistory", __name__)
N02 = import_module(".N02-PlanCompaction", __name__)
N03 = import_module(".N03-GenerateRollingSummary", __name__)
N04 = import_module(".N04-ValidateSummary", __name__)
N05 = import_module(".N05-CommitSummary", __name__)
logger = logging.getLogger(__name__)


async def run_compaction(inputs: CompactionInput, runs: RunStore, summaries: SummaryStore,
                         model: ModelClient | None = None) -> ContextSummary | None:
    """按固定节点顺序执行一次完整压缩，不暴露通用工作流编辑能力。

    Args:
        inputs: 当前账号、历史、预算和需要保留的请求材料快照。
        runs: 原始历史及当前时间线存储。
        summaries: 摘要版本存储。
        model: 可替换的受控摘要模型，默认复用主模型配置并独立限制输出。

    Returns:
        发布的有效摘要；没有触发或任务已失效时为空。

    Raises:
        AgentError: 规划、模型生成或校验失败，旧摘要保持不变。
        OSError: 历史或摘要存储不可用。
    """
    logger.info("Compaction N01-ReadValidHistory owner=%s", inputs.owner)
    source: CompactionSource = N01.read_source(inputs, summaries)
    logger.info("Compaction N02-PlanCompaction owner=%s", inputs.owner)
    plan: CompactionPlan | None = N02.build_plan(inputs, source)
    if plan is None:
        return None
    logger.info("Compaction N03-GenerateRollingSummary owner=%s", inputs.owner)
    content: str = await N03.summarize_history(source.previous.content if source.previous else "", plan.records,
        plan.maximum, plan.prompt.content, model or ChatCompletionsClient(plan.settings), plan.settings)
    logger.info("Compaction N04-ValidateSummary owner=%s", inputs.owner)
    candidate: ContextSummary = N04.validate_summary(inputs, plan, content)
    logger.info("Compaction N05-CommitSummary owner=%s", inputs.owner)
    return N05.commit_summary(inputs.owner, candidate, runs, summaries)
