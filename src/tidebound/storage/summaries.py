"""按账号和时间线保存可追溯的上下文摘要，不修改原始 Run。"""

import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class ContextSummary(BaseModel):
    summary_id: str = Field(default_factory=lambda: uuid4().hex)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    timeline_id: str
    covered_run_ids: list[str]
    content: str
    parent_id: str | None = None
    prompt_name: str
    prompt_hash: str
    model: str
    input_before: int
    input_after: int
    summary_max_bytes: int
    target_input: int | None = None
    target_fallback: bool = False


class SummaryStore:
    """保存不可变摘要版本，以有效历史前缀判断恢复资格。"""

    def __init__(self, root: Path) -> None:
        self.root = root

    def directory(self, owner: str, timeline_id: str) -> Path:
        """将账号与时间线标识限制为合法 UUID 路径。"""
        timeline = UUID(timeline_id).hex if timeline_id else "initial"
        return self.root / UUID(owner).hex / "summaries" / timeline

    def load(self, owner: str, timeline_id: str, run_ids: list[str]) -> ContextSummary | None:
        """读取覆盖当前有效历史前缀最多的摘要，回退后不会读到未来信息。

        Args:
            owner: 已鉴权账号范围。
            timeline_id: 当前有效时间线。
            run_ids: 按历史顺序排列的已提交执行标识。

        Returns:
            有效摘要；没有匹配版本时返回空。

        Raises:
            OSError: 摘要不可读。
            ValueError: 保存的数据损坏。
        """
        versions = [ContextSummary.model_validate_json(path.read_text(encoding="utf-8"))
                    for path in self.directory(owner, timeline_id).glob("*.json")]
        valid = [item for item in versions if item.timeline_id == timeline_id and item.covered_run_ids
                 and item.covered_run_ids == run_ids[:len(item.covered_run_ids)]]
        return max(valid, key=lambda item: (len(item.covered_run_ids), item.created_at), default=None)

    def save(self, owner: str, summary: ContextSummary) -> None:
        """原子写入独立摘要版本，调用方负责写入前的时间线资格检查。

        Args:
            owner: 已鉴权账号范围。
            summary: 已验证来源范围与长度的摘要。

        Raises:
            OSError: 写入失败；旧版本保持不变。
        """
        directory = self.directory(owner, summary.timeline_id)
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{UUID(summary.summary_id).hex}.json"
        temporary = directory / f".{uuid4().hex}.tmp"
        try:
            with temporary.open("x", encoding="utf-8") as output:
                output.write(summary.model_dump_json())
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
