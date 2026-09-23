"""将模型可选的短引用映射回服务端持有的不可改写原文。"""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.tidebound.memory.rolling_summary import conversation_turn
from src.tidebound.runtime.types import RunRecord
from src.tidebound.storage.rolling_summaries import MemoryContent, MemoryEntry, MemoryEvidence


class ReferencedEntry(BaseModel):
    """模型只编写概括并选择引用，不抄写来源身份或原句。"""

    model_config = ConfigDict(extra='forbid', strict=True)
    category: Literal['shared_experience', 'relationship', 'topic', 'agreement', 'preference_boundary']
    content: str = Field(min_length=1, max_length=1500)
    attribution: Literal['user_statement', 'assistant_statement', 'inference']
    event_time: str | None = None
    evidence_refs: list[str] = Field(min_length=1, max_length=8)


class ReferencedContent(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    entries: list[ReferencedEntry] = Field(max_length=50)


@dataclass(frozen=True)
class EvidenceSource:
    """请求内固定的证据映射；unknown 仅供未核实旧稿兼容。"""

    run_ids: tuple[str, ...]
    speaker: Literal['user', 'assistant', 'unknown']
    quote: str


def reference_material(previous: MemoryContent, records: list[RunRecord]) -> tuple[ReferencedContent, dict[str, EvidenceSource]]:
    """建立生成与复核共用的短编号表，原文分块不超过持久化引句上限。

    Args:
        previous: 含历史引句或尚未核实旧条目的摘要。
        records: 本次实际提供的完整原文轮次。

    Returns:
        转为短引用的旧摘要及服务端证据表；编号只在本次请求范围有效。
    """
    sources: dict[str, EvidenceSource] = {}
    identifiers: dict[EvidenceSource, str] = {}

    def add(source: EvidenceSource) -> str:
        """为相同原文复用同一个请求内编号。"""
        if source not in identifiers:
            identifier = f'e{len(sources) + 1}'
            sources[identifier] = source
            identifiers[source] = identifier
        return identifiers[source]

    entries: list[ReferencedEntry] = []
    for entry in previous.entries:
        refs = [add(EvidenceSource((e.run_id,), e.speaker, e.quote)) for e in entry.evidence]
        attribution = entry.attribution
        if not refs:
            refs = [add(EvidenceSource(tuple(entry.source_run_ids), 'unknown', entry.content))]
            attribution = 'inference'
        entries.append(ReferencedEntry(category=entry.category, content=entry.content,
                                       attribution=attribution, event_time=entry.event_time, evidence_refs=refs))
    for record in records:
        turn = conversation_turn(record)
        for speaker in ('user', 'assistant'):
            text = str(turn[speaker])
            for start in range(0, len(text), 100):
                quote = text[start:start + 100]
                if quote.strip():
                    add(EvidenceSource((record.run_id,), speaker, quote))
    return ReferencedContent(entries=entries), sources


def resolve_references(content: ReferencedContent, sources: dict[str, EvidenceSource], *,
                       stage: Literal['draft', 'final'] = 'final') -> MemoryContent:
    """只从服务端映射还原引用，拒绝未知编号和跨说话者冒用。

    Args:
        content: 模型返回的概括及短引用。
        sources: 当前生成与复核共同绑定的证据表。
        stage: 草稿允许把归属错误送入复核；最终结果必须校验归属后才能发布。

    Returns:
        与既有读取工具、存储兼容的完整摘要。

    Raises:
        ValueError: 编号不存在、说话者与归属不符或恢复后结构不合法。
    """
    entries: list[MemoryEntry] = []
    for entry in content.entries:
        selected: list[EvidenceSource] = []
        for ref in dict.fromkeys(entry.evidence_refs):
            if ref not in sources:
                raise ValueError(f'未知证据编号：{ref[:40]}')
            selected.append(sources[ref])
        speaker = {'user_statement': 'user', 'assistant_statement': 'assistant'}.get(entry.attribution)
        if stage == 'final' and speaker and any(source.speaker != speaker for source in selected):
            raise ValueError('证据编号对应的说话者与摘要归属不符')
        evidence = [MemoryEvidence(run_id=s.run_ids[0], speaker=s.speaker, quote=s.quote)
                    for s in selected if s.speaker != 'unknown']
        entries.append(MemoryEntry(category=entry.category, content=entry.content, attribution=entry.attribution,
                                   event_time=entry.event_time,
                                   source_run_ids=list(dict.fromkeys(r for s in selected for r in s.run_ids)),
                                   evidence=evidence))
    return MemoryContent(entries=entries)
