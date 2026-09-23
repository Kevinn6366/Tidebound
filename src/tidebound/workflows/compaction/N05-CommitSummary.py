# ruff: noqa: N999 -- 用户指定 N01-功能 的节点文件命名
"""提交节点：再次核对时间线和来源前缀后原子保存。"""

import asyncio

from src.tidebound.storage.runs import RunStore
from src.tidebound.storage.summaries import ContextSummary, SummaryStore


def commit_summary(owner: str, candidate: ContextSummary, runs: RunStore,
                   summaries: SummaryStore) -> ContextSummary | None:
    """发布仍有资格的摘要，新增对话不影响旧前缀，但重置和取消会使任务失效。

    Args:
        owner: 已鉴权账号范围。
        candidate: 校验节点通过的摘要。
        runs: 读取当前时间线和原始历史的存储。
        summaries: 原子保存摘要版本的存储。

    Returns:
        已保存或更新的现存摘要；任务失效时为空。

    Raises:
        OSError: 来源读取或摘要写入失败。
    """
    task = asyncio.current_task()
    if (task is not None and task.cancelling()) or candidate.timeline_id != runs.current_timeline(owner):
        return None
    active_ids = [item.run_id for item in runs.list_runs(owner)
                  if item.status == "completed" and item.timeline_id == candidate.timeline_id]
    end = len(candidate.covered_run_ids)
    if candidate.covered_run_ids != active_ids[:end]:
        return None
    latest = summaries.load(owner, candidate.timeline_id, active_ids)
    if latest and len(latest.covered_run_ids) >= end:
        return latest
    # 单 worker 中检查与原子写之间不 await，重置不能插入提交中间。
    summaries.save(owner, candidate)
    return candidate
