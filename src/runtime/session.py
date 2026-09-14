"""协调单会话执行、停止与提交，保持模型循环独立。"""
import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from src.config import AgentSettings
from src.debug import TerminalDebug
from src.errors import AgentError
from src.llm import ChatCompletionsClient, ModelClient
from src.prompting import load_character_bundle
from src.runtime.agent_loop import agent_loop
from src.runtime.types import Message, RunRecord
from src.storage.runs import RunStore
from src.tools.registry import create_tools

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
        ZoneInfo(settings.timezone)

    @property
    def configured(self) -> bool:
        return bool(self.settings.mode == "dev" and self.settings.base_url and self.settings.model)

    def records(self, owner: str) -> list[RunRecord]:
        """把无活动任务的遗留 running 记录恢复为中断，不重放工具。

        Args:
            owner: 当前开发范围。

        Returns:
            恢复后的执行列表。
        """
        records = self.store.list_runs(owner)
        for record in records:
            active = self.active.get(owner)
            if record.status == "running" and (active is None or active.record.run_id != record.run_id):
                record.status = "interrupted"
                record.error_code = "run_interrupted"
                record.error = "服务中断了本次回复，本轮未提交。"
                self.store.save(owner, record)
        return records

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
        record = next((item for item in self.records(owner) if item.run_id == run_id), None)
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
        records = self.records(owner)
        existing = next((item for item in records if item.run_id == run_id), None)
        if existing:
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
                           user_content=content, prompt_name=bundle.name)
        history = [item.messages for item in records if item.status == "completed"]
        stop = asyncio.Event()
        self.store.save(owner, record)
        task = asyncio.create_task(self._execute(owner, record, bundle.content, history, stop))
        self.active[owner] = ActiveRun(record, stop, task)
        return record

    async def _execute(self, owner: str, record: RunRecord, system: str,
                       history: list[list[Message]], stop: asyncio.Event) -> None:
        """运行后台任务并在停止资格检查后提交。

        Args:
            owner: 开发归属。
            record: 本轮记录。
            system: 固定的角色提示词。
            history: 开始时的有效历史。
            stop: 设置后不能提交成功结果的停止信号。
        """
        record.messages = [Message(role="user", content=record.user_content)]
        try:
            async with asyncio.timeout(self.settings.timeout_seconds):
                await agent_loop(system, history, record.messages, self.model, self.settings, stop, self.tools)
            if stop.is_set():
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

    async def close(self) -> None:
        """停止并等待当前任务落盘，用于服务关闭。"""
        tasks = list(self.active.values())
        for active in tasks:
            active.stop.set()
        await asyncio.gather(*(active.task for active in tasks), return_exceptions=True)
