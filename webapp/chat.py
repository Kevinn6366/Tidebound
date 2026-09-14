"""对话 HTTP 适配，业务入口位于根目录 backend。"""

from fastapi import APIRouter, HTTPException

from backend.chat import ChatMessageInput, ChatNotConnectedError, submit_message

router = APIRouter()


@router.post("/api/chat/messages")
def create_chat_message(message: ChatMessageInput) -> None:
    """校验对话请求并转交后端空实现。

    Args:
        message: 原对话框提交的正文与附件。

    Raises:
        HTTPException: 后端尚未接入时返回带明确错误码的 501。
    """
    try:
        submit_message(message)
    except ChatNotConnectedError as error:
        raise HTTPException(501, {"code": "chat_not_connected", "message": str(error)}) from error
