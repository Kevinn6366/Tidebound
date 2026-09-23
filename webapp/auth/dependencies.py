"""读取已验证身份并校验账号归属与管理员权限。"""

from fastapi import HTTPException, Request

from src.tidebound.storage.users import User

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
