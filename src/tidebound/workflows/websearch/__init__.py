"""第一反应流 → 对话语境 → 获取搜索资料 → 阅读印象 → 主回复流。"""
import asyncio
from collections.abc import Awaitable, Callable
from importlib import import_module

from src.tidebound.config import AgentSettings
from src.tidebound.llm import ModelClient
from src.tidebound.runtime.events import trace_operation
from src.tidebound.runtime.preview import publish_preview
from src.tidebound.runtime.types import RunRecord

first_reaction = import_module('.N00-FirstReaction', __name__).first_reaction
conversation_context = import_module('.N01-ConversationContext', __name__).conversation_context
retrieve_material = import_module('.N02-Retrieve', __name__).retrieve_material
reading_impression = import_module('.N03-ReadingImpression', __name__).reading_impression


async def search_workflow(query: str, history: list[RunRecord], record: RunRecord,
                          retrieve: Callable[[], Awaitable[dict[str, object]]], model: ModelClient,
                          settings: AgentSettings, stop: asyncio.Event, *,
                          character_system: str | None = None) -> dict[str, object]:
    """顺序执行搜索节点，任何失败都不向主模型回退原始搜索材料。

    Args:
        query: 本次搜索词或兴趣主题。
        history: 当前账号有效对话历史。
        record: 本轮输入和时间线。
        retrieve: 第二节点的受控检索入口，不接受模型指定地址。
        model: 本轮固定的独立搜索模型。
        settings: 本轮配置。
        stop: 执行撤销信号。
        character_system: 本轮固定角色规则，传给可见首段，内部整理节点不使用。

    Returns:
        整理后的印象或供应商安全错误，以及已完成的第一反应。

    Raises:
        AgentError: 停止、节点预算或配置错误。
        ValueError: 节点数据无效。
        OSError: 搜索网络失败。
    """
    with trace_operation(settings, 'workflow', 'websearch') as workflow:
        if not record.reaction_attempted:
            record.reaction_attempted = True
            record.reaction_streaming = True
            try:
                reaction = await first_reaction(record.user_content, query, model, settings, stop,
                                                history=history, timeline_id=record.timeline_id,
                                                character_system=character_system)
                if reaction is not None:
                    record.first_reaction = reaction
                else:
                    publish_preview('')
            finally:
                record.reaction_streaming = False
        context = await conversation_context(history, record, query, model, settings, stop)
        with trace_operation(settings, 'workflow', 'websearch.N02-Retrieve') as outcome:
            result = await retrieve_material(retrieve, stop)
            if isinstance(result.get('error'), str):
                outcome['error_code'] = result['error']
        if 'error' in result:
            workflow['error_code'] = str(result['error'])
        else:
            result = await reading_impression(context, result, model, settings, stop)
        if record.first_reaction:
            result = {**result, 'spoken_reaction': record.first_reaction}
        return result
