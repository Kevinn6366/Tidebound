"""管理员读取本地开发服务日志的固定入口。"""

from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict

from src.tidebound.runtime.model_channels import ChannelsView
from src.tidebound.storage.model_channel import ChannelSelection
from src.tidebound.storage.model_requests import ModelRequestStore, RequestRunSummary, RequestSnapshot, RequestSummary
from webapp.auth.dependencies import require_owner
from webapp.console_log import ConsoleLog, read_debug_log

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
    result = read_debug_log(request.app.state.settings.debug_log_path)
    path = request.app.state.chat.settings.data_dir / 'runtime-events.jsonl'
    events = read_debug_log(path, 500)
    result.events_content = events.content
    if len(events.content.splitlines()) < 500:
        previous = read_debug_log(path.with_suffix('.previous.jsonl'), 500)
        result.events_content = '\n'.join((previous.content + events.content).splitlines()[-500:])
    return result


@router.get("/api/users/{uid}/console/requests")
def list_model_requests(uid: str, request: Request, offset: int = Query(default=0, ge=0)) -> list[RequestSummary]:
    """向管理员分页提供本地服务的模型请求摘要。

    Args:
        uid: 当前登录管理员的 UID。
        request: 携带账号与后端配置的请求。
        offset: 按最新顺序跳过的记录数，每页最多 50 条。

    Returns:
        当前开发服务所有账号的请求摘要，与统一日志的管理员范围一致。

    Raises:
        HTTPException: 未登录、普通用户或跨 UID 访问。
        OSError: 请求记录无法读取。
    """
    require_owner(request, uid, admin=True)
    return ModelRequestStore(request.app.state.chat.settings.data_dir).list_requests(offset)


@router.get("/api/users/{uid}/console/requests/{request_id}")
def get_model_request(uid: str, request_id: UUID, request: Request) -> RequestSnapshot:
    """向管理员返回某次模型请求的完整正文，不应用日志尾部截断。

    Args:
        uid: 当前登录管理员的 UID。
        request_id: 要查看的请求 UUID。
        request: 携带身份和后端配置的请求。

    Returns:
        Run、调用序号及原始请求 JSON 正文，不含 HTTP 请求头。

    Raises:
        HTTPException: 管理员身份或 UID 校验失败。
        AgentError: 快照不存在。
        OSError: 快照无法读取。
    """
    require_owner(request, uid, admin=True)
    return ModelRequestStore(request.app.state.chat.settings.data_dir).get(str(request_id))


@router.get("/api/users/{uid}/console/request-runs")
def list_model_request_runs(uid: str, request: Request, offset: int = Query(default=0, ge=0)) -> list[RequestRunSummary]:
    """按一次用户对话分组返回完整的模型调用子菜单。

    Args:
        uid: 当前登录管理员的 UID。
        request: 带账号身份和后端配置的请求。
        offset: 跳过的对话组数，每页最多 50 组。

    Returns:
        对话组和各组全部请求摘要。

    Raises:
        HTTPException: 非管理员或跨 UID 访问。
        OSError: 请求记录无法读取。
    """
    require_owner(request, uid, admin=True)
    return ModelRequestStore(request.app.state.chat.settings.data_dir).list_request_runs(offset)


@router.get("/api/users/{uid}/console/model-channels")
def get_model_channels(uid: str, request: Request) -> ChannelsView:
    """读取主聊天渠道及配置状态，不返回凭据。

    Args:
        uid: 当前管理员的 UID。
        request: 含鉴权状态和 runtime 的请求。

    Returns:
        服务级主模型选择和两项渠道配置状态。

    Raises:
        HTTPException: 非管理员或跨账号请求。
        OSError: 持久化选择无法读取。
    """
    require_owner(request, uid, admin=True)
    return request.app.state.chat.channels.view()


@router.put("/api/users/{uid}/console/model-channels")
def select_model_channel(uid: str, selection: ChannelSelection, request: Request) -> ChannelsView:
    """切换后续主聊天的服务级渠道，当前执行保留原快照。

    Args:
        uid: 当前管理员的 UID。
        selection: 只包含预定义渠道标识，不接受地址或凭据。
        request: 含鉴权状态和 runtime 的请求。

    Returns:
        持久化成功后的渠道状态。

    Raises:
        HTTPException: 非管理员或跨账号请求。
        AgentError: 渠道未配置或运行模式不支持。
        OSError: 选择保存失败。
    """
    require_owner(request, uid, admin=True)
    return request.app.state.chat.channels.select(selection)


class DebugLoginSetting(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    enabled: bool


@router.put('/api/users/{uid}/console/debug-login')
def set_debug_login(uid: str, setting: DebugLoginSetting, request: Request) -> dict[str, bool]:
    """仅管理员切换本进程免密码调试。

    Args:
        uid: 当前管理员 UID。
        setting: 所需开关状态。
        request: 带登录身份的请求。

    Returns:
        实际生效状态。

    Raises:
        HTTPException: 非管理员或跨账号请求。
        AgentError: 非开发环境。
    """
    require_owner(request, uid, admin=True)
    return {'passwordless_debug': request.app.state.auth.set_passwordless_debug(setting.enabled)}
