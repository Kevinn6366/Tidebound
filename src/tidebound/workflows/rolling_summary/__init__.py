"""使用独立提示词从有效对话增量生成长期关系摘要。"""

import hashlib
import json
from dataclasses import asdict
from importlib import import_module

from src.tidebound.config import AgentSettings
from src.tidebound.context.budget import measure_input
from src.tidebound.context.compaction import input_budget
from src.tidebound.errors import AgentError
from src.tidebound.llm import ModelClient
from src.tidebound.memory.rolling_summary import conversation_turn
from src.tidebound.prompting import load_prompt_bundles
from src.tidebound.runtime.types import Message, RunRecord
from src.tidebound.storage.rolling_summaries import MemoryContent, RollingSummary
from src.tidebound.workflows.rolling_summary.references import reference_material

generate_draft = import_module(f"{__name__}.N01-GenerateSummary").generate_draft
review_summary = import_module(f"{__name__}.N02-ReviewSummary").review_summary
validate_evidence = import_module(f"{__name__}.N02-ReviewSummary").validate_evidence

MAX_BATCHES = 16


def summary_messages(content: MemoryContent, records: list[RunRecord], maximum: int,
                     source_turns: list[RunRecord] | None = None, validation_feedback: str = '') -> list[Message]:
    """构造独立的资料消息，保留来源轮次及讲述时间。

    Args:
        content: 上一版本或上一批次的完整摘要。
        records: 本批新增的完整有效轮次。
        maximum: 输出 JSON 的 UTF-8 字节上限。
        source_turns: 预算内回查的旧条目原始依据，用于纠正来源归属和恢复变化过程。
        validation_feedback: 上次生成失败的校验信息，重试时用于定向纠正。

    Returns:
        不含角色提示词、工具协议或推理内容的输入。
    """
    previous, sources = reference_material(content, [*(source_turns or []), *records])
    return [Message(role='user', content=json.dumps({
        'previous_summary': previous.model_dump(), 'turns': [conversation_turn(r) for r in records],
        'sources': {key: asdict(value) for key, value in sources.items()},
        'source_turns': [conversation_turn(r) for r in (source_turns or [])],
        'summary_max_bytes': maximum,
        'validation_feedback': validation_feedback,
    }, ensure_ascii=False))]


async def generate_summary(previous: RollingSummary | None, records: list[RunRecord],
                           settings: AgentSettings, model: ModelClient, *, validation_feedback: str = '') -> RollingSummary:
    """分批整理所有未覆盖原文，全部通过校验后才返回候选版本。

    Args:
        previous: 与历史前缀匹配的上一版本。
        records: 同一时间线的完整已提交历史快照。
        settings: 独立摘要预算和提示词配置。
        model: 无工具权限的后台模型。
        validation_feedback: 上次尝试的有界校验反馈，不包含工具或推理材料。

    Returns:
        尚未发布的完整摘要，含版本链、覆盖范围和逐项来源。

    Raises:
        AgentError: 单轮超限、批次数超限或模型输出不完整。
        ValueError: JSON、来源或输出大小不合法。
        CancelledError: 后台任务已取消，迟到结果无效。
    """
    prompt = load_prompt_bundles(settings.prompts_dir, ('memory.rolling_summary',)).content
    content = previous.content if previous else MemoryContent(entries=[])
    covered = len(previous.covered_run_ids) if previous else 0
    calls = 0
    while covered < len(records):
        batch: list[RunRecord] = []
        for record in records[covered:]:
            candidate = [*batch, record]
            if measure_input(prompt, summary_messages(content, candidate, settings.rolling_summary_max_bytes, validation_feedback=validation_feedback), []) > input_budget(settings):
                break
            batch = candidate
        if not batch or calls >= MAX_BATCHES:
            raise AgentError('rolling_summary_budget_exceeded', '长期摘要预算不足，保留原版本。', 413)
        # 旧摘要可能已把角色推断写成用户事实；提供原文才能纠错，不能只重复压缩旧结论。
        referenced = {source for entry in content.entries for source in entry.source_run_ids}
        evidence: list[RunRecord] = []
        for record in reversed(records[:covered]):
            if record.run_id not in referenced:
                continue
            candidate = [record, *evidence]
            if measure_input(prompt, summary_messages(content, batch, settings.rolling_summary_max_bytes, candidate, validation_feedback), []) <= input_budget(settings):
                evidence = candidate
        calls += 1
        messages = summary_messages(content, batch, settings.rolling_summary_max_bytes, evidence, validation_feedback)
        _, sources = reference_material(content, [*evidence, *batch])
        draft = await generate_draft(prompt, messages, settings, model, calls * 2 - 1)
        content = await review_summary(prompt, draft, sources, content, [*evidence, *batch],
                                       settings, model, calls * 2)
        # 旧摘要仅允许沿用已有依据，不能凭空引用本批未提供的历史原文。
        allowed = {source for entry in (previous.content.entries if previous else []) for source in entry.source_run_ids}
        allowed.update(r.run_id for r in records[len(previous.covered_run_ids) if previous else 0:covered + len(batch)])
        if any(not set(entry.source_run_ids) <= allowed for entry in content.entries):
            raise ValueError('长期摘要包含未提供的来源')
        covered += len(batch)
    return RollingSummary(timeline_id=records[0].timeline_id, covered_run_ids=[r.run_id for r in records],
                          covered_through_at=records[-1].completed_at or records[-1].created_at,
                          parent_id=previous.summary_id if previous else None, content=content,
                          prompt_hash=hashlib.sha256(prompt.encode()).hexdigest(), model=settings.model)
