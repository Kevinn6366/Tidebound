"""短引用在生成、复核与旧版兼容中的可信边界。"""

import pytest

from src.tidebound.runtime.types import Message, RunRecord
from src.tidebound.storage.rolling_summaries import MemoryContent, MemoryEntry
from src.tidebound.workflows.rolling_summary.references import (
    ReferencedContent,
    ReferencedEntry,
    reference_material,
    resolve_references,
)


def turn(text: str) -> RunRecord:
    return RunRecord(run_id='source-with-a-long-id', created_at='2026-09-22T00:00:00Z', status='completed',
                     user_content=text, messages=[Message(role='assistant', content='**灯芯**，只是我的创作。')])


def test_references_restore_exact_markdown_and_original_id() -> None:
    """两次模型只选择短编号，持久化仍保留原始Markdown和完整来源。"""
    empty = MemoryContent(entries=[])
    original = turn('这是验收情境，不是真实生活。')
    _, sources = reference_material(empty, [original])
    draft = ReferencedContent(entries=[ReferencedEntry(category='topic', content='角色取名灯芯',
        attribution='assistant_statement', evidence_refs=['e2'])])
    result = resolve_references(draft, sources)
    assert result.entries[0].evidence[0].quote == '**灯芯**，只是我的创作。'
    assert result.entries[0].source_run_ids == [original.run_id]
    previous, following = reference_material(result, [])
    assert resolve_references(previous, following) == result
    assert reference_material(empty, [original])[1] == sources


@pytest.mark.parametrize('ref,attribution', [('e999', 'user_statement'), ('e2', 'user_statement')])
def test_unknown_or_wrong_speaker_reference_is_rejected(ref: str, attribution: str) -> None:
    """未知编号和把角色证据用于用户事实均被拒绝。"""
    _, sources = reference_material(MemoryContent(entries=[]), [turn('用户原话')])
    draft = ReferencedContent.model_validate({'entries': [{'category': 'topic', 'content': '概括',
        'attribution': attribution, 'evidence_refs': [ref]}]})
    with pytest.raises(ValueError):
        resolve_references(draft, sources)


def test_legacy_unverified_entry_cannot_be_promoted_to_user_fact() -> None:
    """无引句的旧稿可继续作为未核实记忆，不能变成确定事实。"""
    legacy = MemoryContent(entries=[MemoryEntry(category='topic', content='旧稿说法',
        source_run_ids=['old-run'], attribution='user_statement')])
    draft, sources = reference_material(legacy, [])
    assert draft.entries[0].attribution == 'inference'
    restored = resolve_references(draft, sources)
    assert restored.entries[0].source_run_ids == ['old-run']
    assert restored.entries[0].evidence == []
    draft.entries[0].attribution = 'user_statement'
    with pytest.raises(ValueError):
        resolve_references(draft, sources)


def test_new_turn_chunks_preserve_every_character_and_separate_speakers() -> None:
    """长消息按存储上限分块，不删字、不改标点、不串说话者。"""
    original = turn('验收情境：' + '先Python，后来Markdown。' * 40)
    _, sources = reference_material(MemoryContent(entries=[]), [original])
    quotes = [s.quote for s in sources.values() if s.speaker == 'user']
    assert ''.join(quotes) == original.user_content
    assert all(len(q) <= 100 for q in quotes)


def test_draft_attribution_can_be_reviewed_but_never_published_unchecked() -> None:
    """草稿归属错误允许复核纠正，最终结果仍必须拒绝错误归属。"""
    _, sources = reference_material(MemoryContent(entries=[]), [turn('用户原话')])
    draft = ReferencedContent(entries=[ReferencedEntry(category='topic', content='角色创作',
        attribution='user_statement', evidence_refs=['e2'])])
    assert resolve_references(draft, sources, stage='draft').entries[0].evidence[0].speaker == 'assistant'
    with pytest.raises(ValueError):
        resolve_references(draft, sources)
    draft.entries[0].attribution = 'assistant_statement'
    assert resolve_references(draft, sources).entries[0].attribution == 'assistant_statement'
