# ruff: noqa: N999
"""结合搜索动机整理阅读印象，来源编号仅用于内部校验。"""
import asyncio

from src.tidebound.config import AgentSettings
from src.tidebound.llm import ModelClient
from src.tidebound.workflows.websearch.nodes import SearchContext, SearchImpression, generate


async def reading_impression(context: SearchContext, result: dict[str, object], model: ModelClient,
                             settings: AgentSettings, stop: asyncio.Event) -> dict[str, object]:
    """将搜索摘要整理为自然阅读印象，拒绝模型伪造来源标识。

    Args:
        context: 上游对话语境及搜索原因。
        result: 已规范化的供应商结果，只进入整理节点。
        model: 本轮固定模型。
        settings: 提示词与预算。
        stop: 当前撤销信号。

    Returns:
        阅读印象与不确定性，不包含来源列表或原始搜索摘要数组。

    Raises:
        ValueError: 搜索结构、来源引用或节点结果无效。
        AgentError: 停止、提示词或预算错误。
    """
    rows = result.get('results')
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError('搜索结果结构非法')
    summary = await generate('tools.websearch.impression', {
        'context': context.model_dump(), 'material_kind': 'search_snippets_not_full_pages',
        'sources': [{'id': i, **row} for i, row in enumerate(rows)],
    }, SearchImpression, model, settings, stop)
    if any(i < 0 or i >= len(rows) for i in summary.source_ids) or (rows and not summary.source_ids):
        raise ValueError('阅读印象引用了无效来源')
    return {
        'impression': summary.impression, 'uncertainty': summary.uncertainty,
        'material_kind': 'search_snippets_not_full_pages', 'untrusted': True,
    }
