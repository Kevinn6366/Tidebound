"""对话应用边界：输入校验与视图转换，执行归 src/tidebound/runtime。"""
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.tidebound.context.budget import context_usage
from src.tidebound.errors import AgentError
from src.tidebound.runtime.session import ChatSession
from src.tidebound.runtime.types import ContextUsage, RunRecord


class ContextBudgetInput(BaseModel):
    """管理员可调整的上下文总预算，不接受账号或模型配置。"""

    model_config = ConfigDict(extra="forbid")
    context_limit: int = Field(ge=2048, strict=True)


class ChatAttachment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str
    name: str
    data: str


class ChatMessageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID
    content: str = Field(min_length=1, max_length=24000)
    attachments: list[ChatAttachment] = Field(default_factory=list, max_length=20)

    @field_validator("content")
    @classmethod
    def require_text(cls, value: str) -> str:
        """拒绝空白正文并规范首尾空格。"""
        if not value.strip():
            raise ValueError("正文不能为空")
        return value.strip()


class ToolResultView(BaseModel):
    call_id: str
    name: str
    arguments: str
    result: str | None


class RunView(BaseModel):
    run_id: str
    status: str
    phase: Literal["generating", "compacting"] = "generating"
    tools: list[ToolResultView] = Field(default_factory=list)
    context_usage: ContextUsage | None = None
    preview: str = ""
    user_content: str = ""
    reply: str | None = None
    error_code: str | None = None
    error: str | None = None


class DisplayMessage(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    content: str


class SessionView(BaseModel):
    character: Literal["atri"] = "atri"
    character_name: Literal["亚托莉"] = "亚托莉"
    messages: list[DisplayMessage]
    active_run: RunView | None
    tool_runs: list[RunView]
    context_usage: ContextUsage


def run_view(record: RunRecord) -> RunView:
    """把最终回复、工具记录与安全失败信息交给浏览器。

    Args:
        record: 持久化执行记录。

    Returns:
        不含系统提示词、模型配置或凭据的执行视图。
    """
    reply = record.messages[-1].content if record.status == "completed" else None
    tool_views: list[ToolResultView] = []
    pending: dict[str, ToolResultView] = {}
    for message in record.messages:
        if message.role == "assistant":
            pending = {}
            for call in message.tool_calls:
                view = ToolResultView(call_id=call.id, name=call.name, arguments=call.arguments, result=None)
                pending[call.id] = view
                tool_views.append(view)
        elif message.role == "tool" and message.tool_call_id in pending:
            pending[message.tool_call_id].result = message.content
    return RunView(run_id=record.run_id, status=record.status, phase=record.phase, reply=reply, tools=tool_views,
                   context_usage=record.context_usage, preview=record.preview if record.status == "running" else "", user_content=record.user_content,
                   error_code=record.error_code, error=record.error)


def submit_message(service: ChatSession, owner: str, message: ChatMessageInput) -> RunView:
    """校验首版能力后启动指定归属的执行。

    Args:
        service: 应用组装的会话服务。
        owner: 当前开发范围。
        message: 正文、执行标识和待检查的附件。

    Returns:
        新建或重复执行的状态。

    Raises:
        AgentError: 附件未支持、配置缺失或并发冲突。
    """
    if message.attachments:
        raise AgentError("attachments_not_supported", "v0.01 暂时只支持文字；附件和草稿已保留。", 422)
    return run_view(service.start(owner, str(message.run_id), message.content))


def session_view(service: ChatSession, owner: str) -> SessionView:
    """从已提交记录构建固定 atri 会话的展示历史。

    Args:
        service: 当前会话服务。
        owner: 归属范围。

    Returns:
        仅完成轮次的用户与最终回复，以及当前执行状态。
    """
    messages: list[DisplayMessage] = []
    active = None
    tool_runs: list[RunView] = []
    configured_usage = context_usage(service.settings_for(owner))
    usage = configured_usage
    for record in service.records(owner):
        if record.context_usage is not None and record.status in ("running", "completed"):
            usage = record.context_usage if record.context_usage.total == configured_usage.total else configured_usage
        view = run_view(record)
        if view.tools:
            tool_runs.append(view)
        if record.status == "running":
            active = run_view(record)
        if record.status == "completed":
            messages.extend([
                DisplayMessage(id=f"{record.run_id}:user", role="user", content=record.user_content),
                DisplayMessage(id=f"{record.run_id}:assistant", role="assistant", content=record.messages[-1].content),
            ])
    if active is None:
        usage = service.compacted_usage(owner) or usage
    return SessionView(messages=messages, active_run=active, tool_runs=tool_runs, context_usage=usage)
