# ruff: noqa: N999
"""执行已绑定权限和供应商的检索入口。"""
import asyncio
from collections.abc import Awaitable, Callable

from src.tidebound.workflows.websearch.nodes import check_stop


async def retrieve_material(retrieve: Callable[[], Awaitable[dict[str, object]]],
                            stop: asyncio.Event) -> dict[str, object]:
    """接收搜索返回资料，前后检查撤销，原始内容仅交给下一节点。

    Args:
        retrieve: 服务端绑定的检索方法。
        stop: 当前执行撤销信号。

    Returns:
        规范化的搜索资料或安全错误。

    Raises:
        AgentError: 执行已停止。
        ValueError: 供应商结果格式非法。
        OSError: 外部连接失败。
    """
    check_stop(stop)
    result = await retrieve()
    check_stop(stop)
    return result
