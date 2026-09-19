"""文本提交、状态查询和停止的 HTTP 适配。"""
import asyncio
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from src.tidebound.context.budget import context_usage
from src.tidebound.runtime.types import ContextUsage
from webapp.auth.dependencies import current_user, require_owner
from webapp.chat_service import (
    ChatMessageInput,
    ContextBudgetInput,
    DisplayStartInput,
    RunView,
    SessionView,
    run_view,
    session_view,
    submit_message,
)

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



@router.post("/api/chat/context/reset")
async def reset_chat_context(request: Request) -> SessionView:
    """仅允许管理员清空自身有效上下文并返回初始会话视图。

    Args:
        request: 携带服务端验证身份的请求，不接受其他账号范围参数。

    Returns:
        空聊天历史、空活动执行与初始预算状态。

    Raises:
        HTTPException: 未登录或当前账号不是管理员。
        AgentError: 正在重置。
        OSError: 重置状态无法保存。
    """
    user = current_user(request)
    require_owner(request, user.uid, admin=True)
    await request.app.state.chat.reset_context(user.scope)
    return session_view(request.app.state.chat, user.scope)


@router.get("/api/chat/context/budget")
async def get_context_budget(request: Request) -> ContextUsage:
    """读取当前管理员下一轮使用的预算。

    Args:
        request: 携带已验证身份和会话服务的请求。

    Returns:
        当前配置与回复预留；不混用历史请求用量。

    Raises:
        HTTPException: 未登录或非管理员。
        OSError: 预算读取失败。
    """
    user = current_user(request)
    require_owner(request, user.uid, admin=True)
    return context_usage(request.app.state.chat.settings_for(user.scope))


@router.put("/api/chat/context/budget")
async def update_context_budget(budget: ContextBudgetInput, request: Request) -> ContextUsage:
    """保存当前管理员自己的上下文总预算。

    Args:
        budget: 严格校验的整数预算，不接受其他账号信息。
        request: 携带已验证身份和会话服务的请求。

    Returns:
        下一轮生效的预算配置。

    Raises:
        HTTPException: 未登录或非管理员。
        AgentError: 非开发模式或预算没有留下输入空间。
        OSError: 保存失败。
    """
    user = current_user(request)
    require_owner(request, user.uid, admin=True)
    return context_usage(request.app.state.chat.update_context_budget(user.scope, budget.context_limit))


@router.post("/api/chat/context/compact")
async def compact_chat_context(request: Request) -> ContextUsage:
    """允许开发环境管理员主动压缩自己的上下文并等待结果。

    Args:
        request: 携带已鉴权账号和会话服务的请求，不接受其他账号参数。

    Returns:
        完成压缩后的预算用量。

    Raises:
        HTTPException: 未登录或非管理员。
        AgentError: 当前无法压缩、工作流失败或结果已失效。
    """
    user = current_user(request)
    require_owner(request, user.uid, admin=True)
    return await request.app.state.chat.compact_context(user.scope)


@router.post("/api/chat/meet")
async def prepare_meet(request: Request) -> SessionView:
    """登录后检查是否需要问候，立即返回并由后台继续生成。

    Args:
        request: 已登录账号的请求，不接受外部指定的账号或历史。

    Returns:
        已有历史、欢迎任务和当前活动状态。

    Raises:
        AgentError: 配置不合法或正在清空上下文。
    """
    service = request.app.state.chat
    owner = current_user(request).scope
    service.prepare_meet(owner)
    return session_view(service, owner)


@router.post("/api/chat/meet/retry")
async def retry_meet(request: Request) -> SessionView:
    """显式重试失败的欢迎任务，成功的欢迎保持幂等。

    Args:
        request: 已鉴权的重试请求。

    Returns:
        重试或复用后的会话状态。

    Raises:
        AgentError: 当前配置或会话状态不允许生成。
    """
    service = request.app.state.chat
    owner = current_user(request).scope
    service.prepare_meet(owner, retry=True)
    return session_view(service, owner)


@router.post("/api/chat/meet/test")
async def test_meet(request: Request) -> SessionView:
    """让开发管理员主动测试自身欢迎工作流，跳过登录冷却与已完成欢迎去重。

    Args:
        request: 已鉴权的管理员请求，不接受其他账号或外部历史。

    Returns:
        新建或复用活动欢迎执行后的会话状态。

    Raises:
        HTTPException: 未登录或不是管理员。
        AgentError: 非开发环境、普通对话忙碌或正在清空上下文。
    """
    user = current_user(request)
    require_owner(request, user.uid, admin=True)
    service = request.app.state.chat
    service.prepare_meet(user.scope, trigger="manual")
    return session_view(service, user.scope)


@router.post("/api/chat/runs/{run_id}/display")
async def record_display_start(run_id: UUID, display: DisplayStartInput, request: Request) -> RunView:
    """接收首次逐字展示确认，保存服务端时间供 Log 使用。

    Args:
        run_id: 当前用户正在展示的执行 UUID。
        display: 客户端看到的正文版本，不接受客户端时间。
        request: 携带已鉴权归属的请求。

    Returns:
        展示时间已持久化的执行视图。

    Raises:
        AgentError: 记录不属于用户、正文已失效或尚未生成。
        OSError: 展示时间保存失败。
    """
    return run_view(request.app.state.chat.record_display_start(
        current_user(request).scope, str(run_id), display.revision))
