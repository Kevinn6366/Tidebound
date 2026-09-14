"""使用 python -m uvicorn webapp.main:app 启动独立通信层。"""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from starlette.responses import JSONResponse, Response

from src.config import AgentSettings
from src.errors import AgentError
from src.llm import ModelClient
from src.runtime.session import ChatSession
from webapp.chat import router as chat_router
from webapp.config import WebSettings
from webapp.routes import router
from webapp.ui_routes import router as ui_router


def create_app(settings: WebSettings | None = None, agent_settings: AgentSettings | None = None,
               model: ModelClient | None = None) -> FastAPI:
    """组装固定 atri 的本地开发应用。

    Args:
        settings: 可注入的静态资源路径，省略时使用仓库默认目录。
        agent_settings: 模型、提示词和运行数据配置，省略时读取环境。
        model: 受控测试可注入的模型边界。

    Returns:
        不加载旧模型后端，使用独立 Python 循环的应用。
    """
    chat = ChatSession(agent_settings or AgentSettings.from_env(), model)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        """等待后台执行正常停止后关闭应用。"""
        yield
        await chat.close()

    application = FastAPI(title="Tidebound WebApp", version="0.0.1", lifespan=lifespan)
    application.state.chat = chat
    application.state.settings = settings or WebSettings()

    @application.exception_handler(AgentError)
    async def agent_error(_: Request, error: AgentError) -> JSONResponse:
        """将可公开的业务错误转换为通信错误。"""
        return JSONResponse({"detail": {"code": error.code, "message": str(error)}}, status_code=error.status)

    @application.middleware('http')
    async def preview_identity(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        """为开发预览资源分配浏览器范围，拒绝跨来源写操作。

        Args:
            request: 当前浏览器请求。
            call_next: 后续通信路由调用入口。

        Returns:
            带预览 Cookie 的响应；非法来源或路径直接返回错误。
        """
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            origin = request.headers.get('origin')
            allowed_origins = {str(request.base_url).rstrip('/'), application.state.settings.dev_frontend_origin}
            if origin and origin not in allowed_origins:
                return JSONResponse({'detail': '不接受跨来源写入'}, status_code=403)
        cookie = request.cookies.get('tidebound_preview', '')
        try:
            preview_id = UUID(cookie).hex
        except ValueError:
            preview_id = uuid4().hex
        request.state.preview_id = preview_id
        try:
            response = await call_next(request)
        except ValueError:
            return JSONResponse({'detail': '资源路径或请求数据非法'}, status_code=400)
        if cookie != preview_id:
            response.set_cookie('tidebound_preview', preview_id, httponly=True, samesite='strict', max_age=31_536_000)
        return response

    application.include_router(chat_router)
    application.include_router(ui_router)
    application.include_router(router)
    return application


app = create_app()
