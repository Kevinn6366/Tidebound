"""使用 python -m uvicorn webapp.main:app 启动独立通信层。"""

from collections.abc import Awaitable, Callable
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from starlette.responses import JSONResponse, Response

from webapp.chat import router as chat_router
from webapp.config import WebSettings
from webapp.routes import router
from webapp.ui_routes import router as ui_router


def create_app(settings: WebSettings | None = None) -> FastAPI:
    """组装仅供展示迁移验收使用的 FastAPI 应用。

    Args:
        settings: 可注入的静态资源路径，省略时使用仓库默认目录。

    Returns:
        不加载旧模型后端；设置资源按浏览器隔离的开发预览应用。
    """
    application = FastAPI(title="Tidebound WebApp", version="0.1.0")
    application.state.settings = settings or WebSettings()
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
