"""文本提交、状态查询和停止的 HTTP 适配。"""
from uuid import UUID

from fastapi import APIRouter, Request

from backend.chat import ChatMessageInput, RunView, SessionView, run_view, session_view, submit_message

router = APIRouter()


@router.post("/api/chat/messages", status_code=202)
async def create_chat_message(message: ChatMessageInput, request: Request) -> RunView:
    """提交后立即返回执行标识，断开请求不停止后台任务。

    Args:
        message: 校验后的正文与执行标识。
        request: 携带归属和应用服务的请求。

    Returns:
        可继续查询的执行状态。
    """
    return submit_message(request.app.state.chat, request.state.preview_id, message)


@router.get("/api/chat/session")
async def get_session(request: Request) -> SessionView:
    """读取当前范围的已提交历史。

    Args:
        request: 带归属的请求。

    Returns:
        服务端历史与活动执行。
    """
    return session_view(request.app.state.chat, request.state.preview_id)


@router.get("/api/chat/runs/{run_id}")
async def get_run(run_id: UUID, request: Request) -> RunView:
    """查询当前范围内的指定执行。

    Args:
        run_id: 指定执行 UUID。
        request: 带归属的请求。

    Returns:
        执行视图，不存在时由异常处理器返回 404。
    """
    return run_view(request.app.state.chat.get(request.state.preview_id, str(run_id)))


@router.post("/api/chat/runs/{run_id}/stop")
async def stop_run(run_id: UUID, request: Request) -> RunView:
    """停止指定执行，客户端继续查询最终状态。

    Args:
        run_id: 用户明确停止的执行 UUID。
        request: 带归属的请求。

    Returns:
        当前执行状态，已完成执行保持完成。
    """
    return run_view(request.app.state.chat.stop(request.state.preview_id, str(run_id)))
