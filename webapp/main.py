"""使用 python -m uvicorn webapp.main:app 启动独立通信层。"""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, Response

from backend.auth import AuthService
from src.tidebound.config import AgentSettings
from src.tidebound.errors import AgentError
from src.tidebound.llm import ModelClient
from src.tidebound.runtime.session import ChatSession
from src.tidebound.storage.users import MysqlSettings, MysqlUserStore, UserStore
from webapp.auth import COOKIE_NAME
from webapp.auth import router as auth_router
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
        yield
        await chat.close()

    application = FastAPI(title="Tidebound WebApp", version="0.0.1", lifespan=lifespan)
    application.state.chat = chat
    application.state.settings = settings or WebSettings()
    application.state.auth = AuthService(user_store or MysqlUserStore(MysqlSettings.from_env()))

    @application.exception_handler(AgentError)
    async def agent_error(_: Request, error: AgentError) -> JSONResponse:
        """将可公开的业务错误转换为通信错误。"""
        return JSONResponse({"detail": {"code": error.code, "message": str(error)}}, status_code=error.status)

    @application.middleware("http")
    async def authenticate(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        """解析账号会话并保护所有私有 API，拒绝跨来源写操作。

        Args:
            request: 当前浏览器请求。
            call_next: 后续通信路由调用入口。

        Returns:
            已校验身份的响应，或未登录、跨来源请求的错误。
        """
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            allowed_origins = {str(request.base_url).rstrip("/"), application.state.settings.dev_frontend_origin}
            if (origin and origin not in allowed_origins) or request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"detail": "不接受跨来源写入"}, status_code=403)
        try:
            request.state.user = await run_in_threadpool(application.state.auth.resolve, request.cookies.get(COOKIE_NAME))
        except AgentError as error:
            return JSONResponse({"detail": {"code": error.code, "message": str(error)}}, status_code=error.status)
        claimed_uid = request.headers.get("x-tidebound-uid")
        if claimed_uid and request.state.user and claimed_uid != request.state.user.uid:
            return JSONResponse({"detail": "登录账号已改变，请刷新页面"}, status_code=403)
        path = request.url.path
        public = {"/api/health", "/api/capabilities", "/api/models", "/api/auth/status",
                  "/api/auth/setup", "/api/auth/login", "/api/auth/register", "/api/auth/logout"}
        private_api = path.startswith(("/api/", "/v1/", "/admin/")) or path == "/admin"
        if private_api and path not in public and request.state.user is None:
            return JSONResponse({"detail": "请先登录"}, status_code=401)
        if (path.startswith(("/admin/", "/api/admin/")) or path == "/admin") and request.state.user.role != "admin":
            return JSONResponse({"detail": "仅管理员可访问"}, status_code=403)
        try:
            response = await call_next(request)
        except ValueError:
            return JSONResponse({"detail": "资源路径或请求数据非法"}, status_code=400)
        if private_api or path.startswith("/app/uid-"):
            response.headers["Cache-Control"] = "no-store"
        return response

    application.include_router(auth_router)
    application.include_router(console_router)
    application.include_router(chat_router)
    application.include_router(ui_router)
    application.include_router(router)
    return application


app = create_app()
