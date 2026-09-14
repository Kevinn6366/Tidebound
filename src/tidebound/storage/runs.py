"""单 worker dev 的原子 JSON 执行记录，完成记录即已提交历史。"""
import os
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel

from src.tidebound.runtime.types import RunRecord


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
