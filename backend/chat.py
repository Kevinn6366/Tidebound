"""对话应用接口的空实现，与 FastAPI 无关。"""

from pydantic import BaseModel, ConfigDict, Field


class ChatAttachment(BaseModel):
    """原对话框提交的附件，不在空实现中解析或存储。"""

    model_config = ConfigDict(extra="forbid")
    type: str
    name: str
    data: str


class ChatMessageInput(BaseModel):
    """对话通信输入，不接受客户端拼装的历史、提示词或模型凭据。"""

    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1, max_length=100_000)
    attachments: list[ChatAttachment] = Field(default_factory=list, max_length=20)


class ChatNotConnectedError(Exception):
    """对话执行尚未实现，不能伪造模型回复。"""


def submit_message(message: ChatMessageInput) -> None:
    """保留对话后端调用入口，等待后续接入新的 runtime。

    Args:
        message: 已校验的用户正文与附件；当前不执行、不保存。

    Raises:
        ChatNotConnectedError: 当前始终抛出，表示尚无对话业务实现。
    """
    raise ChatNotConnectedError("对话接口已连接，后端逻辑尚未接入；输入与附件已保留。")
