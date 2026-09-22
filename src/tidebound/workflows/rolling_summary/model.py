"""摘要节点共用的模型请求、预算与审计边界。"""

import asyncio

from src.tidebound.config import AgentSettings
from src.tidebound.context.budget import measure_input
from src.tidebound.context.compaction import input_budget
from src.tidebound.errors import AgentError
from src.tidebound.llm import ModelClient
from src.tidebound.runtime.preview import preview_sink
from src.tidebound.runtime.types import Message
from src.tidebound.storage.model_requests import request_injection, request_purpose, request_step
from src.tidebound.workflows.rolling_summary.references import ReferencedContent


async def request_content(prompt: str, messages: list[Message], settings: AgentSettings,
                          model: ModelClient, step_number: int) -> ReferencedContent:
    """调用无预览的摘要节点并验证响应结构及预算。

    Args:
        prompt: 固定摘要规则。
        messages: 生成或独立复核的材料。
        settings: 本次预算和存储配置。
        model: 无工具的后台模型。
        step_number: 审计调用序号。

    Returns:
        尚待逐字来源校验的结构化候选。

    Raises:
        AgentError: 请求超预算或响应未正常结束。
        ValueError: JSON结构或输出大小不合法。
        asyncio.CancelledError: 后台执行已取消。
    """
    if measure_input(prompt, messages, []) > input_budget(settings):
        raise AgentError('rolling_summary_budget_exceeded', '长期摘要预算不足，保留原版本。', 413)
    preview = preview_sink.set(None)
    purpose = request_purpose.set('memory.rolling_summary')
    step = request_step.set(step_number)
    injection = request_injection.set('')
    try:
        reply = await model.complete(prompt, messages, [])
    finally:
        preview_sink.reset(preview)
        request_purpose.reset(purpose)
        request_step.reset(step)
        request_injection.reset(injection)
    task = asyncio.current_task()
    if task is not None and task.cancelling():
        raise asyncio.CancelledError
    if reply.finish_reason != 'stop' or reply.message.role != 'assistant' or reply.message.tool_calls:
        raise AgentError('invalid_rolling_summary', '长期摘要未完整结束。', 502)
    if len(reply.message.content.encode('utf-8')) > settings.rolling_summary_max_bytes:
        raise ValueError('长期摘要超过字节上限')
    return ReferencedContent.model_validate_json(reply.message.content)


