"""使用 python -m uvicorn webapp.main:app 启动独立通信层。"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from starlette.requests import ClientDisconnect
from starlette.responses import JSONResponse, Response

from src.tidebound.config import AgentSettings
from src.tidebound.errors import AgentError
from src.tidebound.llm import ModelClient
from src.tidebound.runtime.events import emit_event
from src.tidebound.runtime.session import ChatSession
from src.tidebound.storage.users import MysqlSettings, MysqlUserStore, UserStore
from webapp.auth.middleware import authenticate
from webapp.auth.routes import router as auth_router
from webapp.auth.service import AuthService
from webapp.chat import router as chat_router
from webapp.config import WebSettings
from webapp.console import router as console_router
from webapp.routes import router
from webapp.ui_routes import router as ui_router


def create_app(settings: WebSettings | None = None, agent_settings: AgentSettings | None = None,
               model: ModelClient | None = None, user_store: UserStore | None = None) -> FastAPI:
    """组装固定 atri 的本地开发应用。

    Args:
        settings: 可注入的静态资源路径，省略时使用仓库默认目录。
        agent_settings: 模型、提示词和运行数据配置，省略时读取环境。
        model: 受控测试可注入的模型边界。
        user_store: 受控测试可注入的账号存储；正常启动始终使用 MySQL。

    Returns:
        不加载旧模型后端，使用独立 Python 循环的应用。
    """
    chat = ChatSession(agent_settings or AgentSettings.from_env(), model)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        """等待后台执行正常停止后关闭应用。"""
        emit_event(chat.settings, "service", "startup", "ready")
        try:
            yield
        finally:
            await chat.close()
            emit_event(chat.settings, "service", "shutdown", "completed")

    application = FastAPI(title="Tidebound WebApp", version="0.0.4", lifespan=lifespan)
    application.state.chat = chat
    application.state.settings = settings or WebSettings()
    application.state.auth = AuthService(user_store or MysqlUserStore(MysqlSettings.from_env()),
                                           development=application.state.chat.settings.mode == "dev",
                                           debug_state_path=chat.settings.data_dir / "auth" / "debug-login.json")

    @application.exception_handler(AgentError)
    async def agent_error(_: Request, error: AgentError) -> JSONResponse:
        """将可公开的业务错误转换为通信错误。"""
        return JSONResponse({"detail": {"code": error.code, "message": str(error)}}, status_code=error.status)

    @application.exception_handler(ClientDisconnect)
    async def client_disconnect(_: Request, error: ClientDisconnect) -> Response:
        """将读取请求体时的客户端断连标记为中断，避免作为服务故障抛出。

        Args:
            _: 已经断开的 HTTP 请求，不记录正文或认证信息。
            error: Starlette 确认读取请求体期间连接已断开的异常。

        Returns:
            499 中断状态，不返回保存成功；客户端断开后可能无法收到响应。
        """
        return Response(status_code=499)

    application.middleware("http")(authenticate)

    application.include_router(auth_router)
    application.include_router(console_router)
    application.include_router(chat_router)
    application.include_router(ui_router)
    application.include_router(router)
    return application


app = create_app()
