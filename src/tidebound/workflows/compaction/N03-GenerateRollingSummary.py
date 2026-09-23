# ruff: noqa: N999 -- 用户指定 N01-功能 的节点文件命名
"""无工具、无角色提示词的有限滚动摘要工作流。"""

import asyncio
import json

from src.tidebound.config import AgentSettings
from src.tidebound.context.budget import measure_input
from src.tidebound.context.compaction import input_budget
from src.tidebound.errors import AgentError
from src.tidebound.llm import ModelClient
from src.tidebound.runtime.preview import preview_sink
from src.tidebound.runtime.types import Message, RunRecord
from src.tidebound.storage.model_requests import request_injection, request_purpose, request_step

MAX_COMPACTION_CALLS = 16
SUMMARY_ATTEMPTS = 2


def summary_input(previous: str, records: list[RunRecord], maximum: int) -> list[Message]:
    """把旧摘要和新增完整轮次转为资料 JSON，移除模型推理内容。

    Args:
        previous: 上一份摘要正文。
        records: 尚未覆盖的已提交轮次。
        maximum: 新摘要 UTF-8 字节上限。

    Returns:
        单条资料消息，不含可执行的工具协议。
    """
    turns = [{"run_id": record.run_id, "created_at": record.created_at,
              "messages": [message.model_dump(exclude={"reasoning_content"}, exclude_none=True)
                           for message in record.messages]} for record in records]
    return [Message(role="user", content=json.dumps({"previous_summary": previous,
        "turns": turns, "summary_max_bytes": maximum}, ensure_ascii=False))]


async def summarize_history(previous: str, records: list[RunRecord], maximum: int,
                            prompt: str, model: ModelClient, settings: AgentSettings) -> str:
    """分批压缩完整历史，验证每个中间摘要，失败不发布半成品。

    Args:
        previous: 上一份有效摘要。
        records: 本次新增覆盖的轮次。
        maximum: 摘要字节上限。
        prompt: 从 context.compaction 加载的固定指令。
        model: 无工具摘要调用使用的模型客户端。
        settings: 摘要调用自己的输出预留和预算。

    Returns:
        合并所有新增轮次后的完整摘要。

    Raises:
        AgentError: 单轮过大、调用额度不足或摘要非法。
    """
    remaining = list(records)
    calls = 0
    while remaining:
        batch: list[RunRecord] = []
        for record in remaining:
            candidate = [*batch, record]
            if measure_input(prompt, summary_input(previous, candidate, maximum), []) > input_budget(settings):
                break
            batch = candidate
        if not batch:
            raise AgentError("compaction_input_exceeded", "单轮历史超过摘要请求预算，原始历史已保留。", 413)
        for attempt in range(SUMMARY_ATTEMPTS):
            calls += 1
            if calls > MAX_COMPACTION_CALLS:
                raise AgentError("compaction_call_limit", "上下文整理达到调用上限，原摘要保持不变。", 502)
            preview_token = preview_sink.set(None)
            purpose_token = request_purpose.set("context.compaction")
            step_token = request_step.set(calls)
            injection_token = request_injection.set("")
            try:
                reply = await model.complete(prompt, summary_input(previous, batch, maximum), [])
            finally:
                preview_sink.reset(preview_token)
                request_purpose.reset(purpose_token)
                request_step.reset(step_token)
                request_injection.reset(injection_token)
            task = asyncio.current_task()
            if task is not None and task.cancelling():
                raise asyncio.CancelledError
            content = reply.message.content.strip()
            if (reply.finish_reason == "stop" and not reply.message.tool_calls and content
                    and len(content.encode("utf-8")) <= maximum):
                previous = content
                break
            if attempt == SUMMARY_ATTEMPTS - 1:
                raise AgentError("invalid_compaction", "上下文摘要为空、超长或未完整结束，原摘要保持不变。", 502)
        remaining = remaining[len(batch):]
    return previous
