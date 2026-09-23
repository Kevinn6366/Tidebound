# ruff: noqa: N999 -- 用户指定 N01-功能 的节点文件命名
"""读取节点：选取有效历史摘要，形成固定的压缩来源。"""

from src.tidebound.context.compaction import assemble_context
from src.tidebound.prompting import load_prompt_bundles
from src.tidebound.storage.summaries import SummaryStore
from src.tidebound.workflows.compaction.types import CompactionInput, CompactionSource


def read_source(inputs: CompactionInput, store: SummaryStore) -> CompactionSource:
    """读取匹配历史前缀的摘要及注入规则，不接纳未提交轮次。

    Args:
        inputs: 已鉴权并固定时间线的工作流输入。
        store: 用户隔离的摘要存储。

    Returns:
        有效旧摘要、压缩前上下文和静态注入规则。

    Raises:
        ValueError: 来源包含其他时间线或未提交历史。
        AgentError: 提示词无法加载。
        OSError: 摘要无法读取。
    """
    if any(item.status != "completed" or item.timeline_id != inputs.timeline for item in inputs.records):
        raise ValueError("摘要只能读取同一时间线的已提交历史")
    previous = store.load(inputs.owner, inputs.timeline, [item.run_id for item in inputs.records])
    injection = load_prompt_bundles(inputs.settings.prompts_dir, ("context.injection.summary",)).content
    before = assemble_context(inputs.system, inputs.records, inputs.current, inputs.tools, previous, injection)
    return CompactionSource(previous, before, injection)
