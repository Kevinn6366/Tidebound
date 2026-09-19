"""搜索工作流的无工具模型节点，隔离预览并严格验证输出。"""
import asyncio
import json
from typing import TypeVar

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

Result = TypeVar('Result', bound=BaseModel)


class SearchContext(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, str_strip_whitespace=True)
    summary: str = Field(min_length=1, max_length=1600)
    reason: str = Field(min_length=1, max_length=40)


class SearchImpression(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, str_strip_whitespace=True)
    impression: str = Field(min_length=1, max_length=1200)
    uncertainty: str = Field(max_length=400)
    source_ids: list[int] = Field(max_length=5)


def check_stop(stop: asyncio.Event) -> None:
    """停止后不再发起请求或接受迟到输出。

    Args:
        stop: 当前 Run 的撤销信号。

    Raises:
        AgentError: 当前执行已停止。
    """
    if stop.is_set():
        raise AgentError('run_stopped', '本次回复已停止。')


def node_messages(system: str, payload: dict[str, object], settings: AgentSettings) -> list[Message]:
    """检查完整节点材料预算，不静默删除历史片段。

    Args:
        system: 节点提示词。
        payload: 本次完整节点资料。
        settings: 本轮模型预算。

    Returns:
        通过预算验证的输入。

    Raises:
        AgentError: 完整材料超出预算。
    """
    return select_messages(system, [], [Message(role='user', content=json.dumps(payload, ensure_ascii=False))], [], settings)


async def generate(purpose: str, payload: dict[str, object], schema: type[Result],
                   model: ModelClient, settings: AgentSettings, stop: asyncio.Event) -> Result:
    """执行无工具节点并校验结构，节点文字不进入角色流式预览。

    Args:
        purpose: manifest 内的节点提示词标识及 Console 用途。
        payload: 数据材料，不提升为系统指令。
        schema: 节点结果结构。
        model: 本轮固定模型渠道。
        settings: 本轮预算与提示词目录。
        stop: 当前执行撤销信号。

    Returns:
        通过结构和长度校验的节点输出。

    Raises:
        AgentError: 停止、预算不足或提示词无效。
        ValueError: 模型未正常结束或输出结构非法。
    """
    with trace_operation(settings, 'workflow', purpose):
        check_stop(stop)
        system = load_prompt_bundles(settings.prompts_dir, (purpose,)).content
        messages = node_messages(system, payload, settings)
        purpose_token = request_purpose.set(purpose)
        step_token = request_step.set(request_step.get() + 1)
        preview_token = preview_sink.set(None)
        try:
            reply = await model.complete(system, messages, [])
            check_stop(stop)
            if reply.finish_reason != 'stop' or reply.message.role != 'assistant' or reply.message.tool_calls:
                raise ValueError('搜索整理节点未正常结束')
            return schema.model_validate_json(reply.message.content)
        finally:
            request_purpose.reset(purpose_token)
            request_step.reset(step_token)
            preview_sink.reset(preview_token)
