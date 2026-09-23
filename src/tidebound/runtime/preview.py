"""本次模型调用的临时正文回调，不保存为有效历史。"""

from collections.abc import Callable
from contextvars import ContextVar

preview_sink: ContextVar[Callable[[str], None] | None] = ContextVar("preview_sink", default=None)


def publish_preview(content: str) -> None:
    """将当前模型正文快照交给所属 Run 的展示缓冲。

    Args:
        content: 当前模型请求已收到的完整正文，空字符串表示重置。
    """
    sink = preview_sink.get()
    if sink is not None:
        sink(content)
