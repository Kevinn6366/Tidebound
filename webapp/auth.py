"""账号接口与统一身份依赖；URL 中的 UID 不作为登录凭据。"""

from ipaddress import ip_address

from fastapi import APIRouter, HTTPException, Request, Response

from backend.auth import SESSION_SECONDS, Credentials, User

router = APIRouter(prefix="/api/auth")
COOKIE_NAME = "tidebound_session"


def current_user(request: Request) -> User:
    """读取中间件验证的登录身份。

    Args:
        request: 当前请求。

    Returns:
        服务端验证的账号。

    Raises:
        HTTPException: 未登录时返回 401。
    """
    user = request.state.user
    if user is None:
        raise HTTPException(401, "请先登录")
    return user


def require_owner(request: Request, uid: str, *, admin: bool = False) -> User:
    """同时检查路径归属与管理员角色。

    Args:
        request: 当前请求。
        uid: 页面或 API 路径中的目标 UID。
        admin: 此入口是否仅允许管理员。

    Returns:
        拥有访问资格的登录账号。

    Raises:
        HTTPException: UID 不匹配或角色不足时返回 403。
    """
    user = current_user(request)
    if user.uid != uid or (admin and user.role != "admin"):
        raise HTTPException(403, "无权访问该用户或管理员页面")
    return user


def set_session(request: Request, response: Response, user: User) -> User:
    """登录成功后轮换 Cookie，身份由响应模型剔除内部字段。

    Args:
        request: 包含旧 Cookie 的请求。
        response: 待写入新 Cookie 的响应。
        user: 已通过验证的账号。

    Returns:
        当前账号身份。
    """
    token = request.app.state.auth.issue_session(user, request.cookies.get(COOKIE_NAME))
    response.set_cookie(COOKIE_NAME, token, httponly=True, samesite="strict",
                        secure=request.url.scheme == "https", max_age=SESSION_SECONDS)
    return user


@router.get("/status")
def auth_status(request: Request) -> dict[str, bool]:
    """报告是否尚需初始化管理员。

    Args:
        request: 携带账号服务的请求。

    Returns:
        首次启动状态，不包含账号清单。
    """
    return {"setup_required": request.app.state.auth.setup_required}


@router.post("/setup", response_model=User, status_code=201)
def setup_admin(credentials: Credentials, request: Request, response: Response) -> User:
    """仅允许从本机完成一次管理员初始化。

    Args:
        credentials: 首个管理员的用户名与密码。
        request: 当前请求，不信任转发头提供的来源地址。
        response: 用于设置登录 Cookie。

    Returns:
        uid-00000001 管理员身份。

    Raises:
        HTTPException: 非本机访问返回 403。
        AgentError: 已初始化时返回 409。
    """
    host = request.client.host if request.client else ""
    try:
        local = ip_address(host).is_loopback
    except ValueError:
        local = host == "testclient"
    if not local:
        raise HTTPException(403, "首次管理员初始化仅允许本机访问")
    return set_session(request, response, request.app.state.auth.create_user(credentials, setup=True))


@router.post("/register", response_model=User, status_code=201)
def register(credentials: Credentials, request: Request, response: Response) -> User:
    """创建普通用户并登录，客户端不能指定 UID 或角色。

    Args:
        credentials: 新账号用户名与密码。
        request: 当前请求。
        response: 用于设置 Cookie 的响应。

    Returns:
        自动分配 UID 的普通账号。
    """
    return set_session(request, response, request.app.state.auth.create_user(credentials))


@router.post("/login", response_model=User)
def login(credentials: Credentials, request: Request, response: Response) -> User:
    """验证用户名和密码并建立会话。

    Args:
        credentials: 用户名和密码。
        request: 当前请求。
        response: 用于设置 Cookie 的响应。

    Returns:
        登录账号的 UID、名称与角色。
    """
    return set_session(request, response, request.app.state.auth.login(credentials))


@router.get("/me", response_model=User)
def me(request: Request) -> User:
    """返回当前登录身份。

    Args:
        request: 带登录会话的请求。

    Returns:
        当前账号身份。
    """
    return current_user(request)


@router.post("/logout")
def logout(request: Request, response: Response) -> dict[str, bool]:
    """撤销服务端会话并清除 Cookie。

    Args:
        request: 包含会话的请求。
        response: 待清理 Cookie 的响应。

    Returns:
        已完成退出的状态。
    """
    request.app.state.auth.logout(request.cookies.get(COOKIE_NAME))
    response.delete_cookie(COOKIE_NAME)
    return {"ok": True}
