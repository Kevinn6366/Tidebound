# ruff: noqa: N999
"""检索前独立流式输出角色的第一反应，失败不阻断正式搜索。"""
import asyncio

from src.tidebound.config import AgentSettings
from src.tidebound.errors import AgentError
from src.tidebound.llm import ModelClient
from src.tidebound.prompting import load_prompt_bundles
from src.tidebound.runtime.events import emit_event, trace_operation
from src.tidebound.runtime.preview import preview_sink
from src.tidebound.runtime.types import RunRecord
from src.tidebound.storage.model_requests import request_purpose, request_step
from src.tidebound.workflows.websearch.nodes import check_stop, node_messages

REACTION_TIMEOUT_SECONDS = 5
REACTION_COMPLETION_SECONDS = 15
MAX_REACTION_LENGTH = 80
REACTION_STYLES = ('consider', 'confident', 'focus', 'playful', 'warm', 'concise')


async def first_reaction(question: str, query: str, model: ModelClient,
                         settings: AgentSettings, stop: asyncio.Event, *,
                         history: list[RunRecord] | None = None,
                         timeline_id: str | None = None) -> str | None:
    """理解当前问题并独立流式生成第一反应，仅正文片段进入展示。

    Args:
        question: 本轮用户原话。
        query: 主 Agent 选定的主题，用于理解指代，不是事实证据。
        model: 独立搜索模型。
        settings: 节点预算与提示词配置。
        stop: 本轮撤销信号。
        history: 当前账号历史，仅取同时间线已提交的首段作避重复参考。
        timeline_id: 本轮有效时间线，排除清空或回退前的内容。

    Returns:
        正常完成的第一反应；超时或生成错误时返回 None。

    Raises:
        AgentError: 用户停止执行。
        asyncio.CancelledError: 父任务撤销。
    """
    check_stop(stop)
    reactions = [item.first_reaction for item in (history or [])
                 if item.status == 'completed' and item.timeline_id == timeline_id
                 and item.first_reaction]
    # 依据有效历史轮换，避免全局随机状态串号；停止和清空不留下风格计数。
    style = REACTION_STYLES[len(reactions) % len(REACTION_STYLES)]
    sink = preview_sink.get()
    deadline: asyncio.Timeout | None = None
    first_chunk = True

    def stream_reaction(content: str) -> None:
        """转发有界的累计正文，不转发思考或 JSON。

        Args:
            content: 供应商当前累计正文。

        Raises:
            ValueError: 首段超长。
            AgentError: 本轮已停止。
        """
        nonlocal first_chunk
        check_stop(stop)
        if content and first_chunk and deadline is not None:
            first_chunk = False
            deadline.reschedule(asyncio.get_running_loop().time() + REACTION_COMPLETION_SECONDS)
        if len(content) > MAX_REACTION_LENGTH:
            raise ValueError('第一反应过长')
        if sink is not None:
            sink(content)

    purpose = 'tools.websearch.reaction'
    purpose_token = request_purpose.set(purpose)
    step_token = request_step.set(request_step.get() + 1)
    preview_token = preview_sink.set(stream_reaction)
    try:
        with trace_operation(settings, 'workflow', purpose):
            async with asyncio.timeout(REACTION_TIMEOUT_SECONDS) as deadline:
                system = load_prompt_bundles(settings.prompts_dir, (purpose,)).content
                messages = node_messages(system, {
                    'question': question, 'topic': query, 'style': style,
                    'recent_reactions': reactions[-4:],
                }, settings)
                reply = await model.complete(system, messages, [])
                check_stop(stop)
                content = reply.message.content.strip()
                if (reply.finish_reason != 'stop' or reply.message.role != 'assistant'
                        or reply.message.tool_calls or not content):
                    raise ValueError('第一反应未正常结束')
                stream_reaction(content)
                return content
    except (TimeoutError, ValueError, OSError, AgentError) as error:
        check_stop(stop)
        emit_event(settings, 'workflow', 'websearch.first_reaction_fallback', 'failed',
                   error_code=error.code if isinstance(error, AgentError) else type(error).__name__)
        return None
    finally:
        preview_sink.reset(preview_token)
        request_step.reset(step_token)
        request_purpose.reset(purpose_token)
