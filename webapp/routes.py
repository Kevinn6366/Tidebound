"""前端展示与资源读取路由；未迁移业务不转发到旧后端。"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse

from webapp.assets import list_model_assets, resolve_public_file
from webapp.config import WebSettings
from webapp.schemas import CapabilitiesResponse, HealthResponse, LoginConfigResponse, ModelListResponse

router = APIRouter()


@router.get("/api/health")
def get_health() -> HealthResponse:
    return HealthResponse()


@router.get("/api/capabilities")
def get_capabilities() -> CapabilitiesResponse:
    return CapabilitiesResponse()


@router.get("/api/login-config")
def get_login_config() -> LoginConfigResponse:
    return LoginConfigResponse()


@router.get("/api/models")
def get_models(request: Request) -> ModelListResponse:
    """返回前端可选择的共享角色清单。

    Args:
        request: 携带应用实例路径配置的 HTTP 请求。

    Returns:
        保持上游 models 字段结构的角色清单。

    Raises:
        OSError: 当资源目录无法读取时抛出。
    """
    settings: WebSettings = request.app.state.settings
    return ModelListResponse(models=list_model_assets(settings.models_dir))


@router.get("/models/{path:path}")
def get_model_file(path: str, request: Request) -> FileResponse:
    """读取公开的角色资源，不接收任意服务器文件路径。

    Args:
        path: 角色资源根目录内的相对路径。
        request: 携带应用实例路径配置的 HTTP 请求。

    Returns:
        对应的模型、纹理或动作文件。

    Raises:
        HTTPException: 文件不存在或超出公开目录时返回 404。
    """
    settings: WebSettings = request.app.state.settings
    target = resolve_public_file(settings.models_dir, path)
    if target is None:
        raise HTTPException(404, "角色资源不存在")
    return FileResponse(target)


@router.get("/")
@router.get("/app")
def redirect_frontend() -> RedirectResponse:
    return RedirectResponse("/app/")


@router.get("/app/{path:path}")
def get_frontend_file(path: str, request: Request) -> FileResponse:
    """从新的构建目录提供页面与静态文件。

    上游页面使用 hash 路由，缺失资源不能回退为 index.html。

    Args:
        path: 构建目录内的资源路径；空路径表示入口页面。
        request: 携带应用实例路径配置的 HTTP 请求。

    Returns:
        页面或资源文件响应。

    Raises:
        HTTPException: 未构建时返回 503；资源不存在或越界时返回 404。
    """
    settings: WebSettings = request.app.state.settings
    if not path and not (settings.frontend_dist / "index.html").is_file():
        raise HTTPException(503, "前端尚未构建，请在 webfrontend 执行 npm run build")
    target = resolve_public_file(settings.frontend_dist, path or "index.html")
    if target is None:
        raise HTTPException(404, "前端资源不存在")
    return FileResponse(target)


@router.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@router.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@router.api_route("/admin/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@router.get("/admin")
def unavailable_business(path: str = "") -> None:
    """明确拒绝尚未迁移的旧业务接口。

    Args:
        path: 被匹配的旧接口路径，仅用于路由匹配，不转发到旧服务。

    Raises:
        HTTPException: 始终返回 501，避免伪造登录、聊天或保存成功。
    """
    raise HTTPException(501, {"code": "not_migrated", "message": "该功能尚未接入 Tidebound，当前仅支持展示与资源读取。"})
