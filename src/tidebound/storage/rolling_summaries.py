"""独立保存长期摘要及逐项来源，不与上下文压缩产物混用。"""

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class MemoryEvidence(BaseModel):
    """摘要归属的逐字依据，不代表外部事实经过核验。"""

    model_config = ConfigDict(extra='forbid', strict=True)
    run_id: str
    speaker: Literal['user', 'assistant']
    quote: str = Field(min_length=1, max_length=300)


class MemoryEntry(BaseModel):
    """自然语言记忆及可回查的依据；事件时间未知时保持为空。"""

    model_config = ConfigDict(extra='forbid', strict=True)
    category: Literal['shared_experience', 'relationship', 'topic', 'agreement', 'preference_boundary']
    content: str = Field(min_length=1, max_length=1500)
    source_run_ids: list[str] = Field(min_length=1, max_length=32)
    attribution: Literal['user_statement', 'assistant_statement', 'inference']
    event_time: str | None = None
    evidence: list[MemoryEvidence] = Field(default_factory=list, max_length=8)


class MemoryContent(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    entries: list[MemoryEntry] = Field(max_length=50)


class RollingSummary(BaseModel):
    summary_id: str = Field(default_factory=lambda: uuid4().hex)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    timeline_id: str
    covered_run_ids: list[str]
    covered_through_at: str
    parent_id: str | None = None
    content: MemoryContent
    prompt_hash: str
    model: str


class RollingSummaryStore:
    """按账号和有效历史前缀恢复不可变版本，适用于单 worker。"""

    def __init__(self, root: Path) -> None:
        self.root = root

    def directory(self, owner: str, timeline: str) -> Path:
        """将服务端绑定的账号与时间线限制为 UUID 路径。"""
        return self.root / UUID(owner).hex / 'rolling_summaries' / (UUID(timeline).hex if timeline else 'initial')

    def load(self, owner: str, timeline: str, run_ids: list[str]) -> RollingSummary | None:
        """读取未越过当前历史边界的最新版本。

        Args:
            owner: 已鉴权账号。
            timeline: 当前执行绑定的时间线。
            run_ids: 当前执行可见的有序已提交历史。

        Returns:
            覆盖范围最大的有效版本，没有则为空。

        Raises:
            OSError: 文件无法读取。
            ValueError: 已存版本损坏。
        """
        versions = [RollingSummary.model_validate_json(path.read_text(encoding='utf-8'))
                    for path in self.directory(owner, timeline).glob('*.json')]
        valid = [s for s in versions if s.timeline_id == timeline and s.covered_run_ids
                 and s.covered_run_ids == run_ids[:len(s.covered_run_ids)]]
        return max(valid, key=lambda s: (len(s.covered_run_ids), s.created_at), default=None)

    def save(self, owner: str, summary: RollingSummary) -> None:
        """原子发布版本，资格检查须由调用方在同一同步段完成。

        Args:
            owner: 已鉴权账号。
            summary: 已校验来源和预算的候选摘要。

        Raises:
            OSError: 发布失败，旧版本不受影响。
        """
        directory = self.directory(owner, summary.timeline_id)
        directory.mkdir(parents=True, exist_ok=True)
        temporary = directory / f'.{uuid4().hex}.tmp'
        try:
            with temporary.open('x', encoding='utf-8') as output:
                output.write(summary.model_dump_json())
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, directory / f'{UUID(summary.summary_id).hex}.json')
        finally:
            temporary.unlink(missing_ok=True)
