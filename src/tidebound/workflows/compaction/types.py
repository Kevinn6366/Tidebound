"""压缩工作流各节点之间传递的明确数据。"""

from dataclasses import dataclass
from typing import Literal

from src.tidebound.config import AgentSettings
from src.tidebound.context.compaction import PreparedContext
from src.tidebound.prompting import PromptBundle
from src.tidebound.runtime.types import Message, RunRecord
from src.tidebound.storage.summaries import ContextSummary


@dataclass
class CompactionInput:
    owner: str
    timeline: str
    system: str
    records: list[RunRecord]
    current: list[Message]
    tools: list[dict[str, object]]
    settings: AgentSettings
    trigger: Literal["automatic", "manual"] = "automatic"


@dataclass
class CompactionSource:
    previous: ContextSummary | None
    before: PreparedContext
    injection: str


@dataclass
class CompactionPlan:
    source: CompactionSource
    end: int
    records: list[RunRecord]
    maximum: int
    prompt: PromptBundle
    settings: AgentSettings
    target_input: int
    fallback: bool
