"""将内部搜索续答草稿转成用户可见的第二段流，不暴露查询过程。"""
import asyncio
import json

from src.tidebound.config import AgentSettings
from src.tidebound.errors import AgentError
from src.tidebound.llm import ModelClient
from src.tidebound.prompting import load_prompt_bundles
from src.tidebound.runtime.events import trace_operation
from src.tidebound.runtime.preview import preview_sink
from src.tidebound.runtime.types import Message, ModelReply
from src.tidebound.storage.model_requests import request_purpose
from src.tidebound.workflows.websearch.nodes import check_stop, node_messages


async def search_reply(system: str, messages: list[Message], tools: list[dict[str, object]],
                       current: list[Message], model: ModelClient, settings: AgentSettings,
                       stop: asyncio.Event) -> ModelReply:
    """隐藏主模型草稿，沿用本轮角色和已选语境进行独立流式交付。

    Args:
        system: 主模型本轮固定的完整角色、世界观和系统规则。
        messages: 主请求已选取的有效上下文，含摘要与近期对话。
        tools: 主模型当前工具权限。
        current: 本轮原始输入与工具结果，不包含旧历史。
        model: 本轮主聊天模型，表达节点沿用该渠道。
        settings: 提示词、预算和供应商配置。
        stop: 本轮取消信号。

    Returns:
        继续执行的工具请求，或已流式交付的角色回复。

    Raises:
        AgentError: 停止、预算不足或表达节点未正常完成。
        OSError: 模型请求或审计失败。
    """
    token = preview_sink.set(None)
    try:
        draft = await model.complete(system, messages, tools)
    finally:
        preview_sink.reset(token)
    check_stop(stop)
    if draft.finish_reason != 'stop' or draft.message.tool_calls or draft.message.role != 'assistant':
        return draft
    purpose = 'tools.websearch.delivery'
    delivery_rules = load_prompt_bundles(settings.prompts_dir, (purpose,)).content
    # 复用本轮快照，避免最终说话的节点换成简化人格或在途中加载另一版角色。
    delivery_system = system + '\n\n' + delivery_rules
    results: list[str] = []
    for item in current:
        if item.role != 'tool':
            continue
        try:
            value = json.loads(item.content)
        except json.JSONDecodeError:
            value = None
        # 错误的操作状态必须保留，供应商/工具故障措辞留在审计而不作为台词素材。
        results.append(json.dumps({'status': 'not_completed', 'information_status': 'unknown'})
                       if isinstance(value, dict) and 'error' in value else item.content)
    payload: dict[str, object] = {
        'question': next((item.content for item in current if item.role == 'user'), ''),
        'tool_results': results,
        'conversation': [
            {'role': item.role, 'content': item.content}
            for item in messages
            if item.role in ('user', 'assistant') and not item.tool_calls
        ],
    }
    delivery_messages = node_messages(delivery_system, payload, settings)
    purpose_token = request_purpose.set(purpose)
    try:
        with trace_operation(settings, 'workflow', purpose):
            result = await model.complete(delivery_system, delivery_messages, [])
            check_stop(stop)
            if (result.finish_reason != 'stop' or result.message.role != 'assistant'
                    or result.message.tool_calls or not result.message.content.strip()):
                raise AgentError('model_incomplete', '续答表达未完成，本轮未保存。', 502)
            return result
    finally:
        request_purpose.reset(purpose_token)
