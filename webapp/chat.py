"""文本提交、状态查询和停止的 HTTP 适配。"""
import asyncio
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from backend.chat import ChatMessageInput, RunView, SessionView, run_view, session_view, submit_message
from webapp.auth import current_user

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
    return submit_message(request.app.state.chat, current_user(request).scope, message)


@router.get("/api/chat/session")
async def get_session(request: Request) -> SessionView:
    """读取当前范围的已提交历史。

    Args:
        request: 带归属的请求。

    Returns:
        服务端历史与活动执行。
    """
    return session_view(request.app.state.chat, current_user(request).scope)


@router.get("/api/chat/runs/{run_id}")
async def get_run(run_id: UUID, request: Request) -> RunView:
    """查询当前范围内的指定执行。

    Args:
        run_id: 指定执行 UUID。
        request: 带归属的请求。

    Returns:
        执行视图，不存在时由异常处理器返回 404。
    """
    return run_view(request.app.state.chat.get(current_user(request).scope, str(run_id)))


@router.post("/api/chat/runs/{run_id}/stop")
async def stop_run(run_id: UUID, request: Request) -> RunView:
    """停止指定执行，客户端继续查询最终状态。

    Args:
        run_id: 用户明确停止的执行 UUID。
        request: 带归属的请求。

    Returns:
        当前执行状态，已完成执行保持完成。
    """
    return run_view(request.app.state.chat.stop(current_user(request).scope, str(run_id)))


@router.get("/api/chat/runs/{run_id}/events")
async def stream_run(run_id: UUID, request: Request) -> StreamingResponse:
    """推送所属 Run 的临时正文与终态，断开订阅不停止执行。

    Args:
        run_id: 要订阅的执行 UUID。
        request: 带已验证账号的 HTTP 请求。

    Returns:
        SSE 状态快照流，重连立即返回最新正文，终态后关闭。

    Raises:
        AgentError: 当前账号的 Run 不存在。
        HTTPException: 未登录。
    """
    service = request.app.state.chat
    owner = current_user(request).scope
    service.get(owner, str(run_id))

    async def events() -> AsyncIterator[str]:
        """推送变化后的视图；固定短间隔合并供应商密集分片。

        Yields:
            完整的 SSE data 事件，正文快照替换而非累加，重连不会重复文字。
        """
        previous = ""
        while not await request.is_disconnected():
            view = run_view(service.get(owner, str(run_id)))
            payload = view.model_dump_json()
            if payload != previous:
                yield f"data: {payload}\n\n"
                previous = payload
            if view.status != "running":
                return
            await asyncio.sleep(0.03)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
