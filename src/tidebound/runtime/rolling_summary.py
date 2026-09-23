"""每账号串行维护长期摘要，不占用主 Run 的回复状态。"""

import asyncio
import logging

from src.tidebound.config import AgentSettings
from src.tidebound.llm import ChatCompletionsClient, ModelClient
from src.tidebound.runtime.types import RunRecord
from src.tidebound.storage.model_requests import request_run
from src.tidebound.storage.rolling_summaries import RollingSummaryStore
from src.tidebound.storage.runs import RunStore
from src.tidebound.workflows.rolling_summary import generate_summary

logger = logging.getLogger(__name__)


class RollingSummaryCoordinator:
    """合并连续提交，生成期间新增的对话在下一次循环追赶。"""

    def __init__(self, runs: RunStore, settings: AgentSettings, model: ModelClient | None = None) -> None:
        """绑定独立后台预算，默认使用基础模型渠道。

        Args:
            runs: 已鉴权历史的持久化入口。
            settings: 服务启动配置，不继承单轮临时主模型渠道。
            model: 可选后台模型替身。
        """
        self.runs = runs
        self.summaries = RollingSummaryStore(runs.root)
        self.settings = settings.model_copy(update={
            'model': settings.rolling_summary_model or settings.model,
            'context_limit': settings.rolling_summary_context_limit,
            'max_output_tokens': settings.rolling_summary_max_output_tokens,
        })
        self.model = model or ChatCompletionsClient(self.settings)
        self.jobs: dict[str, asyncio.Task[None]] = {}
        self.closed = False

    def schedule(self, owner: str, timeline: str) -> asyncio.Task[None] | None:
        """在成功提交或恢复会话时安排维护，复用同账号任务。

        Args:
            owner: 已鉴权账号。
            timeline: 调度时的有效时间线。

        Returns:
            后台任务；关闭后返回空，不影响主回复。
        """
        if self.closed:
            return None
        current = self.jobs.get(owner)
        if current is not None and not current.done():
            return current
        task = asyncio.create_task(self._maintain(owner, timeline))
        self.jobs[owner] = task
        return task

    def _history(self, owner: str, timeline: str) -> list[RunRecord]:
        """读取一个账号在指定时间线内已正式提交的历史。

        Args:
            owner: 已鉴权账号。
            timeline: 本次维护绑定的时间线。

        Returns:
            按提交历史顺序排列的有效记录。

        Raises:
            OSError: 历史读取失败。
            ValueError: 历史记录损坏。
        """
        return [r for r in self.runs.list_runs(owner) if r.status == 'completed' and r.timeline_id == timeline]

    async def _maintain(self, owner: str, timeline: str) -> None:
        """静默生成并重新验证提交资格，失败保留旧版等待后续调度。

        Args:
            owner: 维护账号。
            timeline: 任务绑定时间线，切换后立即失效。

        Raises:
            CancelledError: 清空或关闭时终止维护。
        """
        try:
            while not self.closed and self.runs.current_timeline(owner) == timeline:
                await asyncio.sleep(self.settings.rolling_summary_delay_seconds)
                if self.closed or self.runs.current_timeline(owner) != timeline:
                    return
                records = self._history(owner, timeline)
                ids = [r.run_id for r in records]
                previous = self.summaries.load(owner, timeline, ids)
                if not ids or (previous and previous.covered_run_ids == ids):
                    return
                token = request_run.set((owner, records[-1].run_id))
                try:
                    async with asyncio.timeout(self.settings.timeout_seconds):
                        # 供应商偶发多余括号等结构错误时只重试一次，仍不发布半成品。
                        feedback = ''
                        for attempt in range(2):
                            try:
                                candidate = await generate_summary(previous, records, self.settings, self.model,
                                                                   validation_feedback=feedback)
                                break
                            except ValueError as error:
                                if attempt:
                                    raise
                                feedback = str(error)[:500]
                                logger.info('Retrying invalid rolling summary owner=%s', owner)
                finally:
                    request_run.reset(token)
                task = asyncio.current_task()
                if self.closed or (task is not None and task.cancelling()):
                    return
                if self.runs.current_timeline(owner) != timeline:
                    return
                current_ids = [r.run_id for r in self._history(owner, timeline)]
                if ids != current_ids[:len(ids)]:
                    return
                latest = self.summaries.load(owner, timeline, current_ids)
                if latest is None or len(latest.covered_run_ids) < len(ids):
                    # 单 worker 中资格检查与原子保存之间不能有 await。
                    self.summaries.save(owner, candidate)
                if current_ids == ids:
                    return
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - 后台失败必须回收且不输出用户正文
            logger.warning('Rolling summary failed owner=%s reason=%s', owner, type(error).__name__)

    async def cancel(self, owner: str) -> None:
        """取消并回收账号维护，清空前等待迟到调用退出。

        Args:
            owner: 要取消的账号。
        """
        task = self.jobs.pop(owner, None)
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def close(self) -> None:
        """关闭维护入口并等待全部后台任务退出。"""
        self.closed = True
        for owner in list(self.jobs):
            await self.cancel(owner)
