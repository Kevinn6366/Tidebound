"""管理员读取本地开发服务日志的固定入口。"""

from fastapi import APIRouter, Request

from backend.console import ConsoleLog, read_debug_log
from webapp.auth import require_owner

router = APIRouter()


@router.get("/api/users/{uid}/console/log")
def get_console_log(uid: str, request: Request) -> ConsoleLog:
    """校验管理员与 UID 后读取固定日志文件的尾部。

    Args:
        uid: URL 中的用户 UID，必须等于已登录管理员。
        request: 携带身份及固定日志路径配置的请求。

    Returns:
        agent-debug.log 的末尾 100 行，单次最多读取 256 KiB。

    Raises:
        HTTPException: 未登录、普通用户或跨 UID 请求时拒绝。
        OSError: 文件读取失败，不伪装成无日志。
    """
    require_owner(request, uid, admin=True)
    return read_debug_log(request.app.state.settings.debug_log_path)
