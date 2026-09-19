# ruff: noqa: N999
"""按时间顺序读取全部有效对话，超预算时分批滚动概括。"""
import asyncio

from src.tidebound.config import AgentSettings
from src.tidebound.errors import AgentError
from src.tidebound.llm import ModelClient
from src.tidebound.prompting import load_prompt_bundles
from src.tidebound.runtime.types import RunRecord
from src.tidebound.workflows.websearch.nodes import SearchContext, check_stop, generate, node_messages


async def conversation_context(history: list[RunRecord], record: RunRecord, query: str,
                               model: ModelClient, settings: AgentSettings,
                               stop: asyncio.Event) -> SearchContext:
    """概括有效对话和搜索目的，长历史分批处理而非只取最近轮次。

    Args:
        history: 当前账号已鉴权的历史。
        record: 当前轮次及其时间线。
        query: 本次搜索词。
        model: 本轮固定模型。
        settings: 节点预算与提示词配置。
        stop: 撤销信号。

    Returns:
        约 200 词的语境摘要及最多 40 字的搜索目的。

    Raises:
        AgentError: 停止或最小片段仍不能满足预算。
        ValueError: 摘要输出无效。
    """
    fragments: list[dict[str, str]] = []
    for turn in history:
        if turn.status != 'completed' or turn.timeline_id != record.timeline_id:
            continue
        # 仅使用用户正文和最终回复，排除工具链、内部思考及管理员审计。
        texts = [('user', turn.user_content)]
        if turn.messages and turn.messages[-1].role == 'assistant' and not turn.messages[-1].tool_calls:
            texts.append(('assistant', turn.messages[-1].content))
        for role, text in texts:
            fragments.extend({'role': role, 'text': text[i:i + 1000]} for i in range(0, len(text), 1000))
    fragments.extend({'role': 'user', 'text': record.user_content[i:i + 1000]}
                     for i in range(0, len(record.user_content), 1000))
    purpose = 'tools.websearch.context'
    system = load_prompt_bundles(settings.prompts_dir, (purpose,)).content
    previous: dict[str, object] | None = None
    pending = fragments or [{'role': 'user', 'text': ''}]
    while pending:
        check_stop(stop)
        batch: list[dict[str, str]] = []
        for fragment in pending:
            try:
                node_messages(system, {'query': query, 'previous': previous, 'conversation': [*batch, fragment]}, settings)
            except AgentError as error:
                if error.code != 'context_budget_exceeded' or not batch:
                    raise
                break
            batch.append(fragment)
        result = await generate(purpose, {'query': query, 'previous': previous, 'conversation': batch},
                                SearchContext, model, settings, stop)
        previous = result.model_dump()
        pending = pending[len(batch):]
    return result
