"""协调单会话执行、停止与提交，保持模型循环独立。"""
import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from src.tidebound.config import AgentSettings
from src.tidebound.context.budget import FORMAT_MARGIN
from src.tidebound.debug import TerminalDebug
from src.tidebound.errors import AgentError
from src.tidebound.llm import ChatCompletionsClient, ModelClient
from src.tidebound.prompting import load_character_bundle
from src.tidebound.runtime.agent_loop import agent_loop
from src.tidebound.runtime.preview import preview_sink
from src.tidebound.runtime.types import ContextUsage, Message, RunRecord
from src.tidebound.storage.model_requests import request_run
from src.tidebound.storage.runs import ContextBudget, RunStore
from src.tidebound.tools.registry import create_tools

logger = logging.getLogger(__name__)


@dataclass
class ActiveRun:
    record: RunRecord
    stop: asyncio.Event
    task: asyncio.Task[None]


class ChatSession:
    """单进程 dev 服务；任务不随 HTTP 请求结束，范围间状态独立。"""

    def __init__(self, settings: AgentSettings, model: ModelClient | None = None) -> None:
        self.settings = settings
        self.model = model or ChatCompletionsClient(settings)
        self.tools = create_tools(settings.timezone)
        self.store = RunStore(settings.data_dir)
        self.active: dict[str, ActiveRun] = {}
        self.resetting: set[str] = set()
        ZoneInfo(settings.timezone)

    def settings_for(self, owner: str) -> AgentSettings:
        """构造账号下一轮使用的配置快照。

        Args:
            owner: 当前账号内部范围。

        Returns:
            合并持久化预算后的独立配置，不修改全局配置。

        Raises:
            OSError: 无法读取预算。
            ValueError: 保存的配置损坏。
        """
        budget = self.store.load_context_budget(owner)
        return self.settings.model_copy(update={} if budget is None else {"context_limit": budget.context_limit})

    def update_context_budget(self, owner: str, context_limit: int) -> AgentSettings:
        """保存下一轮生效的账号预算，当前执行保持开始时的快照。

        Args:
            owner: 经应用层授权的账号内部范围。
            context_limit: 包括输入、输出预留与格式余量的总预算。

        Returns:
            保存后的账号有效配置。

        Raises:
            AgentError: 非开发模式或预算没有留下输入空间。
            ValueError: 预算不是合法整数或小于最低值。
            OSError: 预算保存失败。
        """
        if self.settings.mode != "dev":
            raise AgentError("dev_only", "预算调整仅在开发环境开放。", 403)
        budget = ContextBudget(context_limit=context_limit)
        if context_limit <= self.settings.max_output_tokens + FORMAT_MARGIN:
            raise AgentError("invalid_context_budget", "总预算必须大于回复预留与格式余量之和。", 422)
        self.store.save_context_budget(owner, budget)
        return self.settings_for(owner)

    @property
    def configured(self) -> bool:
        return bool(self.settings.mode == "dev" and self.settings.base_url and self.settings.model)

    def records(self, owner: str, *, include_archived: bool = False) -> list[RunRecord]:
        """恢复遗留执行并读取有效时间线，不重放工具。

        Args:
            owner: 当前开发范围。
            include_archived: 内部查询幂等记录时是否包括重置前的历史。

        Returns:
            恢复后的执行列表，默认仅包含有效时间线。
        """
        records = self.store.list_runs(owner)
        for record in records:
            active = self.active.get(owner)
            if record.status == "running" and (active is None or active.record.run_id != record.run_id):
                record.status = "interrupted"
                record.error_code = "run_interrupted"
                record.error = "服务中断了本次回复，本轮未提交。"
                self.store.save(owner, record)
        timeline_id = self.store.current_timeline(owner)
        return [self.active[owner].record if owner in self.active and item.run_id == self.active[owner].record.run_id
                else item for item in records if include_archived or item.timeline_id == timeline_id]

    def get(self, owner: str, run_id: str) -> RunRecord:
        """查找当前范围的执行。

        Args:
            owner: 当前开发范围。
            run_id: 指定执行 UUID。

        Returns:
            对应执行记录。

        Raises:
            AgentError: 执行不存在。
        """
        active = self.active.get(owner)
        if active is not None and active.record.run_id == run_id:
            return active.record
        record = next((item for item in self.records(owner, include_archived=True) if item.run_id == run_id), None)
        if record is None:
            raise AgentError("run_not_found", "执行不存在。", 404)
        return record

    def start(self, owner: str, run_id: str, content: str) -> RunRecord:
        """在任何 await 前占用会话，同 ID 不重复执行。

        Args:
            owner: 当前开发范围。
            run_id: 客户端执行 UUID，仅在本范围内有效。
            content: 已校验的用户正文。

        Returns:
            新执行或相同 ID 的已有执行。

        Raises:
            AgentError: 配置、并发或提示词不合法。
        """
        if self.settings.mode != "dev":
            raise AgentError("dev_only", "v0.01 只支持本地单 worker dev。", 503)
        if owner in self.resetting:
            raise AgentError("context_resetting", "正在清空上下文，请稍后发送。", 409)
        all_records = self.records(owner, include_archived=True)
        timeline_id = self.store.current_timeline(owner)
        records = [item for item in all_records if item.timeline_id == timeline_id]
        existing = next((item for item in all_records if item.run_id == run_id), None)
        if existing:
            if existing.timeline_id != timeline_id:
                raise AgentError("run_archived", "该执行属于已清空的上下文，不能重新提交。", 409)
            if existing.user_content != content:
                raise AgentError("run_id_conflict", "同一执行标识不能用于不同输入。", 409)
            return existing
        if owner in self.active:
            raise AgentError("session_busy", "当前回复尚未结束，请等待或停止后再发送。", 409)
        url = urlsplit(self.settings.base_url)
        if not self.configured or url.scheme not in ("http", "https") or not url.hostname or url.username or url.password:
            raise AgentError("model_not_configured", "请在后端 .env 配置模型服务地址、模型名和所需凭据。", 503)
        bundle = load_character_bundle(self.settings.prompts_dir)
        record = RunRecord(run_id=run_id, created_at=datetime.now(UTC).isoformat(),
                           user_content=content, prompt_name=bundle.name, timeline_id=timeline_id)
        history = [item.messages for item in records if item.status == "completed"]
        stop = asyncio.Event()
        settings = self.settings_for(owner)
        self.store.save(owner, record)
        task = asyncio.create_task(self._execute(owner, record, bundle.content, history, stop, settings))
        self.active[owner] = ActiveRun(record, stop, task)
        return record

    async def _execute(self, owner: str, record: RunRecord, system: str,
                       history: list[list[Message]], stop: asyncio.Event, settings: AgentSettings) -> None:
        """运行后台任务并在停止资格检查后提交。

        Args:
            owner: 开发归属。
            record: 本轮记录。
            system: 固定的角色提示词。
            history: 开始时的有效历史。
            stop: 设置后不能提交成功结果的停止信号。
            settings: 本轮开始时固定的账号配置快照。
        """
        def update_preview(content: str) -> None:
            """更新未提交正文，停止后忽略迟到分片。

            Args:
                content: 当前模型调用累计返回的正文。
            """
            if not stop.is_set() and record.status == "running":
                record.preview = content

        def update_context(usage: ContextUsage) -> None:
            """记录本次请求的预算用量供页面和终态记录读取。

            Args:
                usage: 已通过预算选取的请求用量。
            """
            record.context_usage = usage

        preview_token = preview_sink.set(update_preview)
        context_token = request_run.set((owner, record.run_id))
        record.messages = [Message(role="user", content=record.user_content)]
        try:
            async with asyncio.timeout(settings.timeout_seconds):
                await agent_loop(system, history, record.messages, self.model, settings, stop, self.tools, update_context)
            if stop.is_set() or record.timeline_id != self.store.current_timeline(owner):
                raise AgentError("run_stopped", "本次回复已停止。")
            record.status = "completed"
        except AgentError as error:
            record.status = "stopped" if error.code == "run_stopped" else "failed"
            record.error_code, record.error = error.code, str(error)
        except TimeoutError:
            record.status, record.error_code, record.error = "failed", "run_timeout", "本次执行超时，本轮未提交。"
        except asyncio.CancelledError:
            record.status, record.error_code, record.error = "interrupted", "run_interrupted", "本次执行被服务中断。"
        except Exception as error:  # noqa: BLE001 - 后台任务必须落盘终态且不泄漏第三方异常正文
            logger.error("Agent execution failed: %s", type(error).__name__)
            record.status, record.error_code, record.error = "failed", "internal_error", "执行失败，本轮未提交。"
        finally:
            preview_sink.reset(preview_token)
            request_run.reset(context_token)
            record.preview = ""
            TerminalDebug(self.settings.debug, record.run_id[:8]).write("执行状态", f"{record.status}: {record.error_code or 'ok'}\n")
            try:
                # 检查与原子写之间无 await，停止不能插入成功提交中间。
                self.store.save(owner, record)
            except OSError:
                logger.error("Run persistence failed: %s", record.run_id)
            finally:
                self.active.pop(owner, None)

    def stop(self, owner: str, run_id: str) -> RunRecord:
        """撤销指定执行的提交资格，旧请求不停止较新的任务。

        Args:
            owner: 当前开发范围。
            run_id: 指定执行 UUID。

        Returns:
            当前状态；活动任务随后落盘为 stopped。
        """
        record = self.get(owner, run_id)
        active = self.active.get(owner)
        if active and active.record.run_id == run_id:
            active.stop.set()
        return record

    async def reset_context(self, owner: str) -> None:
        """撤销旧执行并切换到空历史，等待活动任务退出后允许新输入。

        Args:
            owner: 经应用层验证可重置的账号内部范围。

        Raises:
            AgentError: 同一账号正在重置。
            OSError: 新时间线保存失败。
        """
        if owner in self.resetting:
            raise AgentError("context_resetting", "正在清空上下文，请稍后。", 409)
        self.resetting.add(owner)
        try:
            self.store.reset_context(owner)
            active = self.active.get(owner)
            if active is not None:
                active.stop.set()
                active.record.preview = ""
                await asyncio.shield(active.task)
        finally:
            self.resetting.discard(owner)

    async def close(self) -> None:
        """停止并等待当前任务落盘，用于服务关闭。"""
        tasks = list(self.active.values())
        for active in tasks:
            active.stop.set()
        await asyncio.gather(*(active.task for active in tasks), return_exceptions=True)
