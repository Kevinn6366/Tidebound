# ruff: noqa: N999 -- 沿用工作流顺序节点文件命名
"""独立复核摘要，恢复证据并校验最终候选。"""

import json
from dataclasses import asdict

from src.tidebound.config import AgentSettings
from src.tidebound.llm import ModelClient
from src.tidebound.memory.rolling_summary import conversation_turn
from src.tidebound.runtime.types import Message, RunRecord
from src.tidebound.storage.rolling_summaries import MemoryContent
from src.tidebound.workflows.rolling_summary.model import request_content
from src.tidebound.workflows.rolling_summary.references import EvidenceSource, ReferencedContent, resolve_references


def validate_evidence(content: MemoryContent, previous: MemoryContent, records: list[RunRecord]) -> None:
    """校验说话者与逐字依据，阻止把角色引句标为用户事实。

    Args:
        content: 本批候选条目。
        previous: 允许沿用已保存引句的旧条目。
        records: 本次实际提供的新增及回查原文。

    Raises:
        ValueError: 缺少确定归属的证据、说话者不符或引句不在提供的原文中。
    """
    turns = {r.run_id: conversation_turn(r) for r in records}
    inherited = {(e.run_id, e.speaker, e.quote) for entry in previous.entries for e in entry.evidence}
    for entry in content.entries:
        speaker = {'user_statement': 'user', 'assistant_statement': 'assistant'}.get(entry.attribution)
        if speaker is not None and not entry.evidence:
            raise ValueError('确定归属的摘要必须提供原文引句')
        for evidence in entry.evidence:
            if evidence.run_id not in entry.source_run_ids or (speaker and evidence.speaker != speaker):
                raise ValueError('摘要引句的来源或说话者与归属不符')
            turn = turns.get(evidence.run_id)
            if turn is not None:
                if evidence.quote not in str(turn[evidence.speaker]):
                    raise ValueError('摘要引句不是对应说话者的原文')
            elif (evidence.run_id, evidence.speaker, evidence.quote) not in inherited:
                raise ValueError('摘要引句没有可回查依据')


async def review_summary(prompt: str, draft: ReferencedContent, sources: dict[str, EvidenceSource],
                         previous: MemoryContent, records: list[RunRecord], settings: AgentSettings,
                         model: ModelClient, step_number: int) -> MemoryContent:
    """独立审核草稿并验证恢复后的大小、说话者及原文证据。

    Args:
        prompt: 与生成节点一致的固定摘要规则。
        draft: 生成节点返回的短引用草稿。
        sources: 本批生成与复核共用的服务端证据表。
        previous: 允许继承证据的上一批摘要。
        records: 本批实际提供的新增及回查原文。
        settings: 摘要模型和输出预算配置。
        model: 无工具权限的独立复核客户端。
        step_number: 本次复核的审计步骤编号。

    Returns:
        已恢复原始证据且通过校验的完整摘要内容。

    Raises:
        AgentError: 复核请求超预算或响应未完整结束。
        ValueError: 引用、说话者、原文或输出大小不合法。
        asyncio.CancelledError: 本次复核已取消。
    """
    candidate = resolve_references(draft, sources, stage='draft')
    messages = [Message(role='user', content=json.dumps({
        'review_candidate': draft.model_dump(),
        'candidate_persisted_bytes': len(candidate.model_dump_json().encode()),
        'sources': {key: asdict(value) for key, value in sources.items()},
        'summary_max_bytes': settings.rolling_summary_max_bytes,
    }, ensure_ascii=False))]
    reviewed = await request_content(prompt, messages, settings, model, step_number)
    candidate = resolve_references(reviewed, sources)
    if len(candidate.model_dump_json().encode()) > settings.rolling_summary_max_bytes:
        raise ValueError('还原证据后的摘要超过字节上限，请减少重复条目或引用')
    validate_evidence(candidate, previous, records)
    return candidate
