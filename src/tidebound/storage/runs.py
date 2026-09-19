"""单 worker dev 的原子 JSON 执行记录，完成记录即已提交历史。"""
import os
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from src.tidebound.runtime.types import RunRecord


class ContextBudget(BaseModel):
    """账号自己的上下文总预算覆盖值。"""

    context_limit: int = Field(ge=2048, strict=True)


class ContextState(BaseModel):
    """当前有效对话时间线，旧记录默认属于初始空标识。"""

    timeline_id: str


class RunStore:
    """按开发会话范围隔离的文件存储。"""

    def __init__(self, root: Path) -> None:
        self.root = root

    def save(self, owner: str, record: RunRecord) -> None:
        """将完成标记与消息一起原子写入。

        Args:
            owner: 经通信层确定的开发范围。
            record: 需要可靠保存的执行记录。

        Raises:
            OSError: 写入失败，调用方不可宣称提交成功。
        """
        directory = self.root / UUID(owner).hex
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{UUID(record.run_id).hex}.json"
        temporary = directory / f".{uuid4().hex}.tmp"
        try:
            with temporary.open("x", encoding="utf-8") as output:
                output.write(record.model_dump_json())
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    def list_runs(self, owner: str) -> list[RunRecord]:
        """按创建时间读取一个范围的执行记录。

        Args:
            owner: 当前开发会话范围。

        Returns:
            有序执行列表，包含失败记录。

        Raises:
            OSError: 无法读取文件。
            ValueError: 标识或记录损坏。
        """
        records = [RunRecord.model_validate_json(path.read_text(encoding="utf-8"))
                   for path in (self.root / UUID(owner).hex).glob("*.json")]
        return sorted(records, key=lambda record: (record.created_at, record.run_id))


    def current_timeline(self, owner: str) -> str:
        """读取账号的有效时间线，兼容没有状态文件的旧会话。

        Args:
            owner: 经鉴权确定的账号内部范围。

        Returns:
            当前时间线标识；初始会话返回空字符串。

        Raises:
            OSError: 状态文件无法读取。
            ValueError: 状态文件损坏。
        """
        path = self.root / UUID(owner).hex / "state" / "context.json"
        try:
            return ContextState.model_validate_json(path.read_text(encoding="utf-8")).timeline_id
        except FileNotFoundError:
            return ""

    def reset_context(self, owner: str) -> str:
        """原子切换到空时间线，保留旧 Run 和模型请求审计文件。

        Args:
            owner: 要重置的账号内部范围。

        Returns:
            新时间线标识。

        Raises:
            OSError: 无法保存新时间线，不宣称重置成功。
        """
        directory = self.root / UUID(owner).hex / "state"
        directory.mkdir(parents=True, exist_ok=True)
        state = ContextState(timeline_id=uuid4().hex)
        temporary = directory / f".{uuid4().hex}.tmp"
        try:
            with temporary.open("x", encoding="utf-8") as output:
                output.write(state.model_dump_json())
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, directory / "context.json")
        finally:
            temporary.unlink(missing_ok=True)
        return state.timeline_id

    def load_context_budget(self, owner: str) -> ContextBudget | None:
        """读取账号预算覆盖，没有配置时沿用服务端默认值。

        Args:
            owner: 经鉴权确定的账号内部范围。

        Returns:
            已保存的预算；首次配置前为空。

        Raises:
            OSError: 文件无法读取。
            ValueError: 保存的预算格式损坏。
        """
        path = self.root / UUID(owner).hex / "state" / "budget.json"
        try:
            return ContextBudget.model_validate_json(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None

    def save_context_budget(self, owner: str, budget: ContextBudget) -> None:
        """原子保存账号预算，独立于时间线重置。

        Args:
            owner: 经鉴权确定的账号内部范围。
            budget: 已校验的账号上下文预算。

        Raises:
            OSError: 保存失败，不宣称已应用配置。
        """
        directory = self.root / UUID(owner).hex / "state"
        directory.mkdir(parents=True, exist_ok=True)
        temporary = directory / f".{uuid4().hex}.tmp"
        try:
            with temporary.open("x", encoding="utf-8") as output:
                output.write(budget.model_dump_json())
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, directory / "budget.json")
        finally:
            temporary.unlink(missing_ok=True)

    def delete_conversation_history(self, owner: str) -> None:
        """主动清空后删除原始对话与摘要，留下无正文的执行墓碑阻止旧请求重放。

        Args:
            owner: 已切换时间线且活动任务已经退出的账号。

        Raises:
            OSError: 文件删除或墓碑保存失败；不可宣称清空成功。
            ValueError: 历史文件损坏。
        """
        import shutil

        for record in self.list_runs(owner):
            record.user_content = ''
            record.messages = []
            record.first_reaction = ""
            record.reaction_display_started_at = None
            record.companion_state = None
            if record.status == 'completed':
                record.status = 'interrupted'
            record.error_code = 'history_deleted'
            record.error = None
            self.save(owner, record)
        directory = self.root / UUID(owner).hex / 'summaries'
        if directory.exists():
            shutil.rmtree(directory)
