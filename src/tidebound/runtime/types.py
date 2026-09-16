"""循环、模型适配和存储共同使用的轻量消息类型。"""

from typing import Literal

from pydantic import BaseModel, Field


class ToolCall(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    arguments: str


class Message(BaseModel):
    role: Literal["user", "assistant", "tool"]
    content: str = ""
    reasoning_content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_call_id: str | None = None


class ModelReply(BaseModel):
    message: Message
    finish_reason: str


class ContextUsage(BaseModel):
    """最近一次实际模型请求的保守预算占用，空用量表示尚未请求。"""

    total: int
    input_used: int | None = None
    output_reserved: int
    format_margin: int


class RunRecord(BaseModel):
    run_id: str
    created_at: str
    timeline_id: str = ""
    status: Literal["running", "completed", "stopped", "failed", "interrupted"] = "running"
    user_content: str
    messages: list[Message] = Field(default_factory=list)
    preview: str = Field(default="", exclude=True)
    phase: Literal["generating", "compacting"] = Field(default="generating", exclude=True)
    context_usage: ContextUsage | None = None
    prompt_name: str = ""
    error_code: str | None = None
    error: str | None = None
