"""协调静默后台压缩；仅在请求已无法容纳时等待摘要。"""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from src.tidebound.config import AgentSettings
from src.tidebound.context.compaction import (
    PreparedContext,
    assemble_context,
    input_budget,
    needs_compaction,
)
from src.tidebound.debug import TerminalDebug
from src.tidebound.errors import AgentError
from src.tidebound.llm import ModelClient
from src.tidebound.prompting import load_prompt_bundles
from src.tidebound.runtime.types import Message, RunRecord
from src.tidebound.storage.model_requests import request_run
from src.tidebound.storage.runs import RunStore
from src.tidebound.storage.summaries import ContextSummary, SummaryStore
from src.tidebound.workflows.compaction import run_compaction
from src.tidebound.workflows.compaction.types import CompactionInput

logger = logging.getLogger(__name__)


@dataclass
class CompactionJob:
    task: asyncio.Task[ContextSummary | None]
    timeline_id: str


class CompactionCoordinator:
    """每个账号最多一个后台任务，已提交历史可以与后续主回复并行读取。"""

    def __init__(self, root_store: RunStore, model: ModelClient | None = None) -> None:
        self.runs = root_store
        self.summaries = SummaryStore(root_store.root)
        self.model = model
        self.jobs: dict[str, CompactionJob] = {}
        self.closed = False

    def read_context(self, owner: str, timeline: str, system: str, records: list[RunRecord],
                     current: list[Message], tools: list[dict[str, object]],
                     settings: AgentSettings) -> tuple[PreparedContext, ContextSummary | None]:
        """读取匹配历史的摘要并组装请求，不把本轮未提交消息作为摘要来源。

        Args:
            owner: 已鉴权账号范围。
            timeline: 当前 Run 的时间线快照。
            system: 角色和当次临时规则。
            records: Run 开始时的已提交历史。
            current: 当前轮次原文。
            tools: 主模型工具声明。
            settings: 当前 Run 的配置快照。

        Returns:
            完整上下文和实际使用的摘要版本。

        Raises:
            AgentError: 提示词无效。
            OSError: 摘要无法读取。
        """
        summary = self.summaries.load(owner, timeline, [item.run_id for item in records])
        injection = load_prompt_bundles(settings.prompts_dir, ("context.injection.summary",)).content if summary else ""
        return assemble_context(system, records, current, tools, summary, injection), summary

    def schedule(self, owner: str, timeline: str, system: str, records: list[RunRecord],
                 current: list[Message], tools: list[dict[str, object]], settings: AgentSettings,
                 audit_run_id: str, *, trigger: Literal["automatic", "manual"] = "automatic") -> asyncio.Task[ContextSummary | None] | None:
        """达到阈值时调度静默后台任务，复用同账号已经在进行的任务。

        Args:
            owner: 已鉴权账号范围。
            timeline: 任务所属时间线。
            system: 仅用于规划预算的角色和临时规则，不发给摘要模型。
            records: 已提交历史的固定快照。
            current: 仅用于规划保留空间的当前消息，不参与摘要。
            tools: 仅用于主请求预算的工具声明。
            settings: 本次预算与模型配置快照。
            audit_run_id: Console 请求记录所属的 Run。
            trigger: 自动检查阈值，手动入口跳过阈值检查。

        Returns:
            已调度或正在运行的任务；不需压缩时为空。
        """
        if self.closed:
            return None
        job = self.jobs.get(owner)
        if job and not job.task.done():
            return job.task
        task = asyncio.create_task(self._compact(owner, timeline, system, list(records), list(current),
                                                 tools, settings, audit_run_id, trigger))
        self.jobs[owner] = CompactionJob(task, timeline)
        return task

    async def _compact(self, owner: str, timeline: str, system: str, records: list[RunRecord],
                       current: list[Message], tools: list[dict[str, object]], settings: AgentSettings,
                       audit_run_id: str, trigger: Literal["automatic", "manual"] = "automatic") -> ContextSummary | None:
        """生成候选摘要并在同一时间线下原子发布，后台失败仅记录日志。

        Args:
            owner: 摘要归属账号。
            timeline: 压缩开始时的时间线。
            system: 用于计算压缩后预算的主提示词。
            records: 已提交历史快照。
            current: 压缩后仍需容纳的当前消息。
            tools: 主请求工具定义。
            settings: 压缩开始时的配置快照。
            audit_run_id: 用于关联模型请求审计的执行标识。
            trigger: 本次由阈值检查或管理员主动触发。

        Returns:
            发布的摘要；未达到阈值、失效或失败时为空。
        """
        token = request_run.set((owner, audit_run_id))
        try:
            async with asyncio.timeout(settings.timeout_seconds):
                candidate = await run_compaction(
                    CompactionInput(owner, timeline, system, records, current, tools, settings, trigger),
                    self.runs, self.summaries, self.model)
                if candidate:
                    TerminalDebug(settings.debug, "Compaction").write("N05-CommitSummary",
                        f"input={candidate.input_before}->{candidate.input_after}, "
                        f"summary_bytes={len(candidate.content.encode())}, fallback={candidate.target_fallback}\n")
                    logger.info("Context compacted owner=%s timeline=%s summary=%s input=%d->%d covered=%d",
                                owner, timeline, candidate.summary_id, candidate.input_before,
                                candidate.input_after, len(candidate.covered_run_ids))
                return candidate
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - 后台异常必须取回，且不能泄漏模型响应正文
            TerminalDebug(settings.debug, "Compaction").write("failed",
                f"{error.code if isinstance(error, AgentError) else type(error).__name__}\n")
            logger.warning("Context compaction failed owner=%s timeline=%s reason=%s", owner, timeline,
                           error.code if isinstance(error, AgentError) else type(error).__name__)
            return None
        finally:
            request_run.reset(token)

    async def prepare(self, owner: str, timeline: str, system: str, records: list[RunRecord],
                      current: list[Message], tools: list[dict[str, object]], settings: AgentSettings,
                      audit_run_id: str, stop: asyncio.Event,
                      on_wait: Callable[[], None] | None = None) -> PreparedContext:
        """优先采用现成摘要；原请求装不下时才等待后台任务，不静默裁剪历史。

        Args:
            owner: 当前账号。
            timeline: 当前 Run 时间线。
            system: 当次主请求的固定和临时规则。
            records: 当前 Run 的已提交历史快照。
            current: 当前轮次输入与完整工具链。
            tools: 当前可用工具声明。
            settings: 当前 Run 预算配置。
            audit_run_id: 主 Run 审计标识。
            stop: 当前主执行的停止信号；不影响基于旧已提交历史的后台任务。
            on_wait: 主请求必须等待工作流时通知会话展示整理状态；静默后台压缩不调用。

        Returns:
            满足输入预算的完整上下文。

        Raises:
            AgentError: 用户停止或压缩后仍无法放入请求。
        """
        # 第一份后台摘要可能按上一轮的材料规划；至多再按本轮材料压缩一次。
        for _ in range(2):
            prepared, previous = self.read_context(owner, timeline, system, records, current, tools, settings)
            task = None
            if needs_compaction(prepared.input_used, settings):
                task = self.schedule(owner, timeline, system, records, current, tools, settings, audit_run_id)
            if prepared.input_used <= input_budget(settings):
                return prepared
            if task is None:
                break
            if on_wait is not None:
                on_wait()
            stopped = asyncio.create_task(stop.wait())
            try:
                await asyncio.wait({task, stopped}, return_when=asyncio.FIRST_COMPLETED)
                if stop.is_set():
                    raise AgentError("run_stopped", "本次回复已停止。")
            finally:
                stopped.cancel()
                await asyncio.gather(stopped, return_exceptions=True)
            prepared, latest = self.read_context(owner, timeline, system, records, current, tools, settings)
            if prepared.input_used <= input_budget(settings):
                return prepared
            if latest == previous:
                break
        if prepared.input_used > input_budget(settings):
            raise AgentError("context_budget_exceeded", "上下文暂时无法整理到可用预算，请重试或调整服务端预算。", 413)
        return prepared

    async def cancel(self, owner: str) -> None:
        """取消并回收账号的后台任务，供时间线重置使用。

        Args:
            owner: 要重置的账号范围。
        """
        job = self.jobs.pop(owner, None)
        if job:
            job.task.cancel()
            await asyncio.gather(job.task, return_exceptions=True)

    async def close(self) -> None:
        """关闭后台压缩并等待任务退出，不再允许发布摘要。"""
        self.closed = True
        for owner in list(self.jobs):
            await self.cancel(owner)
