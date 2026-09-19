# ruff: noqa: N999
"""只根据已校验用户证据整理跟进摘要。"""
import asyncio
import json

from pydantic import BaseModel, ConfigDict, Field

from src.tidebound.config import AgentSettings
from src.tidebound.context.budget import select_messages
from src.tidebound.errors import AgentError
from src.tidebound.llm import ModelClient
from src.tidebound.prompting import load_prompt_bundles
from src.tidebound.runtime.events import trace_operation
from src.tidebound.runtime.preview import preview_sink
from src.tidebound.runtime.types import Message
from src.tidebound.storage.model_requests import request_purpose, request_step


class FollowupSummary(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, str_strip_whitespace=True)
    summary: str = Field(min_length=1, max_length=300)
    condition: str = Field(min_length=1, max_length=200)


async def summarize(payload: dict[str, object], model: ModelClient,
                    settings: AgentSettings, stop: asyncio.Event) -> FollowupSummary:
    """执行一次有预算的无工具摘要调用，返回经结构校验的摘要。

    Args:
        payload: 操作、现有事项以及来自用户正文的证据。
        model: 运行时绑定的摘要模型。
        settings: 本次执行的预算和提示词配置。
        stop: 当前执行撤销信号。

    Returns:
        摘要和自然跟进条件，不代表已建立定时提醒。

    Raises:
        AgentError: 执行停止、预算不足或模型输出不完整。
        ValueError: 摘要不是所要求的 JSON 结构。
    """
    with trace_operation(settings, 'workflow', 'followup.N01-Summarize'):
        system = load_prompt_bundles(settings.prompts_dir, ('workflow.followup',)).content
        messages = select_messages(system, [], [Message(role='user', content=json.dumps(payload, ensure_ascii=False))], [], settings)
        purpose = request_purpose.set('workflow.followup')
        step = request_step.set(request_step.get() + 1)
        preview = preview_sink.set(None)
        try:
            if stop.is_set():
                raise AgentError('run_stopped', '本次回复已停止。')
            reply = await model.complete(system, messages, [])
            if stop.is_set():
                raise AgentError('run_stopped', '本次回复已停止。')
            if reply.finish_reason != 'stop' or reply.message.tool_calls or reply.message.role != 'assistant':
                raise ValueError('跟进摘要未正常结束')
            return FollowupSummary.model_validate_json(reply.message.content)
        finally:
            request_purpose.reset(purpose)
            request_step.reset(step)
            preview_sink.reset(preview)
