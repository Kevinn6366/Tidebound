"""HTTP 会话解析、私有入口保护与跨来源写入限制。"""

from collections.abc import Awaitable, Callable

from fastapi import Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, RedirectResponse, Response

from src.tidebound.errors import AgentError
from webapp.auth.dependencies import COOKIE_NAME


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
        allowed_origins = {str(request.base_url).rstrip("/"), request.app.state.settings.dev_frontend_origin}
        if (origin and origin not in allowed_origins) or request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"detail": "不接受跨来源写入"}, status_code=403)
    try:
        request.state.user = await run_in_threadpool(request.app.state.auth.resolve, request.cookies.get(COOKIE_NAME))
    except AgentError as error:
        return JSONResponse({"detail": {"code": error.code, "message": str(error)}}, status_code=error.status)
    claimed_uid = request.headers.get("x-tidebound-uid")
    if claimed_uid and request.state.user and claimed_uid != request.state.user.uid:
        return JSONResponse({"detail": "登录账号已改变，请刷新页面"}, status_code=403)
    path = request.url.path
    if path.startswith("/app/uid-") and request.state.user is None:
        return RedirectResponse("/app/", status_code=303, headers={"Cache-Control": "no-store"})
    public = {"/api/health", "/api/capabilities", "/api/models", "/api/auth/status",
              "/api/auth/setup", "/api/auth/login", "/api/auth/debug-login", "/api/auth/register", "/api/auth/logout"}
    private_api = path.startswith(("/api/", "/v1/", "/admin/")) or path == "/admin"
    if private_api and path not in public and request.state.user is None:
        return JSONResponse({"detail": "Unauthorized"}, status_code=401, headers={"Cache-Control": "no-store"})
    if (path.startswith(("/admin/", "/api/admin/")) or path == "/admin") and request.state.user.role != "admin":
        return JSONResponse({"detail": "仅管理员可访问"}, status_code=403)
    try:
        response = await call_next(request)
    except ValueError:
        return JSONResponse({"detail": "资源路径或请求数据非法"}, status_code=400)
    if private_api or path.startswith("/app/uid-"):
        response.headers["Cache-Control"] = "no-store"
    return response
