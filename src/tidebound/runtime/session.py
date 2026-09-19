"""协调单会话执行、停止与提交，保持模型循环独立。"""
import asyncio
import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from urllib.parse import urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo

from src.tidebound.config import AgentSettings
from src.tidebound.context.budget import FORMAT_MARGIN, context_usage
from src.tidebound.context.compaction import PreparedContext
from src.tidebound.debug import TerminalDebug
from src.tidebound.errors import AgentError
from src.tidebound.llm import ChatCompletionsClient, ModelClient
from src.tidebound.prompting import load_chat_system, load_prompt_bundles
from src.tidebound.runtime.agent_loop import agent_loop
from src.tidebound.runtime.compaction import CompactionCoordinator
from src.tidebound.runtime.companion import companion_context, load_state
from src.tidebound.runtime.events import emit_event, trace_operation
from src.tidebound.runtime.model_channels import ModelChannels
from src.tidebound.runtime.preview import preview_sink
from src.tidebound.runtime.types import ContextUsage, Message, RunRecord
from src.tidebound.storage.model_requests import request_run
from src.tidebound.storage.runs import ContextBudget, RunStore
from src.tidebound.tools.companion.operations import CompanionTools
from src.tidebound.tools.registry import create_tools, register_companion_tools, tool_definitions
from src.tidebound.workflows.meet import run_meet

WELCOME_INTERVAL = timedelta(minutes=30)

logger = logging.getLogger(__name__)


@dataclass
class ActiveRun:
    record: RunRecord
    stop: asyncio.Event
    task: asyncio.Task[None]


class ChatSession:
    """单进程 dev 服务；任务不随 HTTP 请求结束，范围间状态独立。"""

    def __init__(self, settings: AgentSettings, model: ModelClient | None = None,
                 summary_model: ModelClient | None = None, meet_model: ModelClient | None = None) -> None:
        """组装账号隔离的聊天与后台工作流服务。

        Args:
            settings: 服务端模型、时区、提示词和持久化配置。
            model: 普通聊天测试替身，提供时也作为未单独指定的工作流替身。
            summary_model: 独立摘要模型替身，省略时沿用现有摘要配置。
            meet_model: 独立欢迎模型替身，省略时使用欢迎配置或通用测试替身。

        Raises:
            ZoneInfoNotFoundError: 配置的时区不可用。
        """
        self.settings = settings
        self.model = model
        self.channels = ModelChannels(settings)
        self.meet_model = meet_model or model
        self.tools = create_tools(settings.timezone)
        self.store = RunStore(settings.data_dir)
        self.compaction = CompactionCoordinator(self.store, summary_model or model)
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
        return self.channels.resolve().model_copy(update={} if budget is None else {"context_limit": budget.context_limit})

    def companion_budget_material(self, records: list[RunRecord], settings: AgentSettings
                                  ) -> tuple[str, list[Message], list[dict[str, object]]]:
        """为空闲预算和主动压缩构造与主执行相同的工具、规则和状态资料。

        Args:
            records: 当前时间线已提交历史。
            settings: 当前账号预算配置。

        Returns:
            完整 system、状态资料及最近一次联网权限对应的工具声明。
        """
        state = load_state(records)
        record = records[-1] if records else RunRecord(run_id=str(uuid4()), created_at='', user_content='')
        registry = create_tools(settings.timezone)
        service = CompanionTools(records, record, state, self.model or ChatCompletionsClient(settings), settings, asyncio.Event())
        register_companion_tools(registry, service, internet_enabled=record.internet_enabled)
        system, material = companion_context(load_chat_system(settings.prompts_dir).content, state, settings, record.run_id)
        return system, material, tool_definitions(registry)

    def compacted_usage(self, owner: str) -> ContextUsage | None:
        """返回后台摘要发布后的当前上下文估算，让空闲页面及时显示释放的空间。

        Args:
            owner: 已鉴权账号范围。

        Returns:
            已应用摘要的预算；没有有效摘要时为空，保持原展示兼容。

        Raises:
            AgentError: 当前提示词无法加载。
            OSError: 历史或摘要无法读取。
        """
        records = [item for item in self.records(owner) if item.status == "completed"]
        timeline = self.store.current_timeline(owner)
        if self.compaction.summaries.load(owner, timeline, [item.run_id for item in records]) is None:
            return None
        settings = self.settings_for(owner)
        system, material, tools = self.companion_budget_material(records, settings)
        prepared, _ = self.compaction.read_context(owner, timeline, system, records, material, tools, settings)
        return context_usage(settings, prepared.input_used)

    async def compact_context(self, owner: str) -> ContextUsage:
        """主动整理当前账号的已提交历史，复用后台任务且不生成聊天消息。

        Args:
            owner: 已由通信层验证权限的账号范围。

        Returns:
            成功发布摘要后的预算用量。

        Raises:
            AgentError: 非开发模式、正在回复或重置、没有新增历史、压缩失败或结果失效。
            OSError: 历史或摘要无法读取。
        """
        if self.settings.mode != "dev":
            raise AgentError("dev_only", "主动压缩仅在开发环境开放。", 403)
        if owner in self.resetting or owner in self.active:
            raise AgentError("context_busy", "请等待当前回复或清空操作结束后再整理上下文。", 409)
        settings = self.settings_for(owner)
        records = [item for item in self.records(owner) if item.status == "completed"]
        timeline = self.store.current_timeline(owner)
        previous = self.compaction.summaries.load(owner, timeline, [item.run_id for item in records])
        if not records or (previous and len(previous.covered_run_ids) >= len(records)):
            raise AgentError("nothing_to_compact", "暂无新增的已完成对话可压缩。", 409)
        system, material, tools = self.companion_budget_material(records, settings)
        task = self.compaction.schedule(owner, timeline, system,
            records, material, tools, settings, records[-1].run_id, trigger="manual")
        if task is None:
            raise AgentError("compaction_unavailable", "整理服务正在关闭，请稍后重试。", 503)
        try:
            result = await asyncio.shield(task)
        except asyncio.CancelledError:
            if not task.cancelled():
                raise
            raise AgentError("compaction_cancelled", "整理已取消，上下文可能已被清空。", 409) from None
        if self.store.current_timeline(owner) != timeline:
            raise AgentError("compaction_stale", "上下文已变化，本次整理结果不再适用。", 409)
        if result is None:
            raise AgentError("compaction_failed", "整理未成功，原文和原摘要已保留；请检查预算或查看日志后重试。", 502)
        return context_usage(settings, result.input_after)

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
        settings = self.channels.resolve()
        return bool(settings.mode == "dev" and settings.base_url and settings.model)

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

    def start(self, owner: str, run_id: str, content: str, *, internet_enabled: bool = False) -> RunRecord:
        """在任何 await 前占用会话，同 ID 不重复执行。

        Args:
            owner: 当前开发范围。
            run_id: 客户端执行 UUID，仅在本范围内有效。
            content: 已校验的用户正文。
            internet_enabled: 本轮是否允许使用联网工具，默认关闭。

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
            if existing.user_content != content or existing.internet_enabled != internet_enabled:
                raise AgentError("run_id_conflict", "同一执行标识不能用于不同输入。", 409)
            return existing
        if owner in self.active:
            raise AgentError("session_busy", "当前回复尚未结束，请等待或停止后再发送。", 409)
        settings = self.settings_for(owner)
        url = urlsplit(settings.base_url)
        if not settings.model or url.scheme not in ("http", "https") or not url.hostname or url.username or url.password:
            raise AgentError("model_not_configured", "请在后端 .env 配置模型服务地址、模型名和所需凭据。", 503)
        bundle = load_chat_system(self.settings.prompts_dir)
        record = RunRecord(run_id=run_id, created_at=datetime.now(UTC).isoformat(),
                           user_content=content, prompt_name=bundle.name, timeline_id=timeline_id, track_display_time=True,
                           internet_enabled=internet_enabled)
        history = [item for item in records if item.status == "completed"]
        stop = asyncio.Event()
        self.store.save(owner, record)
        task = asyncio.create_task(self._execute(owner, record, bundle.content, history, stop, settings))
        self.active[owner] = ActiveRun(record, stop, task)
        return record

    def record_display_start(self, owner: str, run_id: str, revision: int) -> RunRecord:
        """记录页面首次开始展示正文的服务端时间，不等同于已读或生成完成。

        Args:
            owner: 已鉴权账号范围。
            run_id: 页面正在逐字展示的执行标识。
            revision: 正文预览版本，拒绝工具过渡文字或旧请求的迟到确认。

        Returns:
            包含首次展示时间的执行；重复请求保持原时间，旧记录不补造时间。

        Raises:
            AgentError: 时间线、正文版本或执行状态已经失效。
            OSError: 展示时间无法持久化。
        """
        record = self.get(owner, run_id)
        if (record.timeline_id != self.store.current_timeline(owner) or record.display_revision != revision
                or record.status not in ("running", "completed")):
            raise AgentError("display_stale", "该正文已失效，不记录展示时间。", 409)
        if not record.track_display_time or record.display_started_at:
            return record
        if record.status == "running" and not record.preview:
            raise AgentError("display_not_ready", "正文尚未开始展示。", 409)
        timestamp = datetime.now(UTC).isoformat()
        # 保存成功后再更新活动对象，写入失败允许下一次展示确认重试。
        self.store.save(owner, record.model_copy(update={"display_started_at": timestamp}))
        record.display_started_at = timestamp
        if record.preview_stage == "reaction":
            record.reaction_display_started_at = timestamp
        return record

    def prepare_meet(self, owner: str, *, retry: bool = False,
                     trigger: Literal["login", "manual"] = "login") -> RunRecord | None:
        """登录时预生成问候，已存在的欢迎尝试只在显式重试时重做。

        Args:
            owner: 经鉴权的账号范围，不能由请求正文指定。
            retry: 用户明确要求重试失败、停止或中断的欢迎任务。
            trigger: 登录检查或开发管理员手动测试；手动测试跳过冷却和已完成欢迎去重。

        Returns:
            已有或新建的欢迎执行；无需欢迎或普通聊天忙碌时为空。

        Raises:
            AgentError: 服务未配置、重置中或提示词非法。
            OSError: 历史或初始执行记录无法读写。
        """
        if trigger == "manual" and self.settings.mode != "dev":
            raise AgentError("dev_only", "主动欢迎测试仅在开发环境开放。", 403)
        if owner in self.resetting:
            raise AgentError("context_resetting", "正在清空上下文，请稍后。", 409)
        if owner in self.active:
            active = self.active[owner].record
            if trigger == "manual" and active.kind != "meet":
                raise AgentError("session_busy", "当前回复尚未结束，请等待或停止后再测试。", 409)
            return active if active.kind == "meet" else None
        records = self.records(owner)
        history = [item for item in records if item.status == "completed"]
        last_chat_index = max((i for i, item in enumerate(records)
                               if item.kind == "chat" and item.status == "completed"), default=-1)
        previous = next((item for item in reversed(records[last_chat_index + 1:]) if item.kind == "meet"), None)
        if trigger != "manual" and previous and (previous.status == "completed" or not retry):
            return previous
        now = datetime.now(UTC)
        if history and trigger != "manual":
            last_time = datetime.fromisoformat(history[-1].completed_at or history[-1].created_at)
            if last_time.tzinfo is None:
                last_time = last_time.replace(tzinfo=UTC)
            if now - last_time <= WELCOME_INTERVAL:
                return None
        settings = self.settings_for(owner).model_copy(update={
            "model": self.settings.meet_model,
            "base_url": self.settings.meet_base_url or self.settings.base_url,
            "api_key": self.settings.meet_api_key if self.settings.meet_api_key.get_secret_value() else self.settings.api_key,
            "max_output_tokens": 1024, "reasoning_effort": "low",
            "timeout_seconds": self.settings.meet_timeout_seconds,
        })
        url = urlsplit(settings.base_url)
        if (settings.mode != "dev" or not settings.model or url.scheme not in ("http", "https")
                or not url.hostname or url.username or url.password):
            raise AgentError("model_not_configured", "请在后端配置欢迎模型服务。", 503)
        bundle = load_chat_system(settings.prompts_dir)
        # 开始前验证必需包；失败不会占用会话或产生伪造用户消息。
        load_prompt_bundles(settings.prompts_dir, ("chat.meet",))
        record = RunRecord(run_id=str(uuid4()), created_at=now.isoformat(), kind="meet",
                           user_content="", prompt_name="chat.meet", timeline_id=self.store.current_timeline(owner),
                           track_display_time=True)
        stop = asyncio.Event()
        self.store.save(owner, record)
        task = asyncio.create_task(self._execute(owner, record, bundle.content, history, stop, settings))
        self.active[owner] = ActiveRun(record, stop, task)
        return record

    async def _execute(self, owner: str, record: RunRecord, system: str,
                       history: list[RunRecord], stop: asyncio.Event, settings: AgentSettings) -> None:
        """运行后台任务并在停止资格检查后提交。

        Args:
            owner: 开发归属。
            record: 本轮记录。
            system: 固定的角色提示词。
            history: 开始时的有效历史。
            stop: 设置后不能提交成功结果的停止信号。
            settings: 本轮开始时固定的账号配置快照。
        """
        state = load_state(history)
        registry = create_tools(settings.timezone)
        model = self.model or ChatCompletionsClient(settings)
        search_settings = settings.model_copy(update={
            'model': self.settings.websearch_model,
            'base_url': self.settings.websearch_base_url or self.settings.base_url,
            'api_key': self.settings.websearch_api_key if self.settings.websearch_api_key.get_secret_value() else self.settings.api_key,
        })
        companion = CompanionTools(history, record, state, model, settings, stop,
                                   websearch_model=self.model or ChatCompletionsClient(search_settings))
        register_companion_tools(registry, companion, internet_enabled=record.internet_enabled)

        def update_preview(content: str) -> None:
            """更新未提交正文，停止后忽略迟到分片。

            Args:
                content: 当前模型调用累计返回的正文。
            """
            if not stop.is_set() and record.status == "running":
                if record.reaction_streaming:
                    record.preview_stage = "reaction"
                    record.preview = content
                elif record.first_reaction:
                    stage = "answer" if content else "reaction"
                    if record.preview_stage != stage:
                        record.display_revision += 1
                        record.display_started_at = record.reaction_display_started_at if stage == "reaction" else None
                    record.preview_stage = stage
                    record.preview = content or record.first_reaction
                else:
                    if not content:
                        record.display_revision += 1
                        record.display_started_at = None
                    record.preview_stage = "answer"
                    record.preview = content

        def update_context(usage: ContextUsage) -> None:
            """记录本次请求的预算用量供页面和终态记录读取。

            Args:
                usage: 已通过预算选取的请求用量。
            """
            record.context_usage = usage

        async def prepare_context(request_system: str, current: list[Message],
                                  tools: list[dict[str, object]]) -> PreparedContext:
            """获取已完成摘要，预算不足时等待后台压缩。

            Args:
                request_system: 主模型的角色与本次工具规则。
                current: 当前轮次消息原文。
                tools: 当前工具声明。

            Returns:
                满足预算的模型上下文。

            Raises:
                AgentError: 停止或上下文仍超限。
            """
            def mark_compacting() -> None:
                """仅在主执行确实等待工作流时展示整理状态，摘要正文不进入预览。"""
                if record.status == "running" and not stop.is_set():
                    record.phase = "compacting"
                    record.preview = record.first_reaction

            try:
                request_system, material = companion_context(request_system, state, settings, record.run_id)
                return await self.compaction.prepare(owner, record.timeline_id, request_system, history,
                    [*material, *current], tools, settings, record.run_id, stop, on_wait=mark_compacting)
            finally:
                record.phase = "generating"

        started_at = time.monotonic()
        emit_event(settings, "run", record.kind, "started", run=(owner, record.run_id))
        preview_token = preview_sink.set(update_preview)
        context_token = request_run.set((owner, record.run_id))
        record.messages = [] if record.kind == "meet" else [
            Message(role="user", content=record.user_content, created_at=record.created_at)]
        try:
            async with asyncio.timeout(settings.timeout_seconds):
                if record.kind == "meet":
                    injection = load_prompt_bundles(settings.prompts_dir, ("chat.meet",)).content
                    event = Message(role="user", content=json.dumps({
                        "event": "first_meet" if not history else "return_meet",
                        "current_time": datetime.now(ZoneInfo(settings.timezone)).isoformat(),
                        "timezone": settings.timezone,
                        "last_dialogue_at": (history[-1].completed_at or history[-1].created_at) if history else None,
                    }, ensure_ascii=False))
                    prepared = await prepare_context(f"{system}\n\n{injection}", [event], [])
                    update_context(context_usage(settings, prepared.input_used))
                    # 欢迎先完整生成，页面等待期间不展示未校验的半成品。
                    preview_sink.set(None)
                    with trace_operation(settings, 'workflow', 'meet'):
                        message = await run_meet(prepared, self.meet_model or ChatCompletionsClient(settings), injection, stop)
                    record.messages = [message]
                else:
                    await agent_loop(system, [item.messages for item in history], record.messages,
                                     model, settings, stop, registry, update_context, prepare_context)
            if stop.is_set() or record.timeline_id != self.store.current_timeline(owner):
                raise AgentError("run_stopped", "本次回复已停止。")
            if record.first_reaction and not record.messages[-1].content.startswith(record.first_reaction):
                record.messages[-1].content = record.first_reaction + "\n\n" + record.messages[-1].content
            record.completed_at = datetime.now(UTC).isoformat()
            record.messages[-1].created_at = record.completed_at
            record.companion_state = state
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
            if record.status != "completed":
                record.first_reaction = ""
                record.reaction_display_started_at = None
            try:
                # 检查与原子写之间无 await，停止不能插入成功提交中间。
                self.store.save(owner, record)
            except OSError:
                record.status, record.error_code = "failed", "persistence_failed"
                record.error = "回复保存失败，本轮未提交。"
                emit_event(settings, "storage", "commit_run", "failed", run=(owner, record.run_id), error_code="persistence_failed")
                logger.error("Run persistence failed: %s", record.run_id)
            else:
                emit_event(settings, "storage", "commit_run", "completed", run=(owner, record.run_id))
                if record.status == "completed":
                    try:
                        maintenance = self.settings_for(owner) if record.kind == "meet" else settings
                        maintenance_system, material = companion_context(system, state, maintenance, record.run_id)
                        self.compaction.schedule(owner, record.timeline_id, maintenance_system, [*history, record], material,
                                                 tool_definitions(registry), maintenance, record.run_id)
                    except (OSError, ValueError):
                        logger.error("Post-commit compaction scheduling failed: %s", record.run_id)
            finally:
                emit_event(settings, "run", record.kind, record.status, run=(owner, record.run_id),
                           duration_ms=round((time.monotonic() - started_at) * 1000), error_code=record.error_code or "")
                TerminalDebug(self.settings.debug, record.run_id[:8]).write("执行状态", f"{record.status}: {record.error_code or 'ok'}\n")
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
            await self.compaction.cancel(owner)
            self.store.delete_conversation_history(owner)
        finally:
            self.resetting.discard(owner)

    async def close(self) -> None:
        """停止并等待当前任务落盘，用于服务关闭。"""
        tasks = list(self.active.values())
        for active in tasks:
            active.stop.set()
        await asyncio.gather(*(active.task for active in tasks), return_exceptions=True)
        await self.compaction.close()
