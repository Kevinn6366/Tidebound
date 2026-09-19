"""读取开发服务的固定调试日志，不接受客户端文件路径。"""

from pathlib import Path

from pydantic import BaseModel

LOG_TAIL_LINES = 100
MAX_LOG_TAIL_BYTES = 256 * 1024


class ConsoleLog(BaseModel):
    filename: str = "agent-debug.log"
    content: str
    exists: bool
    truncated: bool = False
    events_content: str = ""


def read_debug_log(path: Path, line_limit: int = LOG_TAIL_LINES) -> ConsoleLog:
    """有界读取日志末尾 100 行，兼容追加、截断与文件轮换。

    Args:
        path: 由后端配置的固定日志文件，不能来自 URL 参数。
        line_limit: 服务端固定的最大显示行数。

    Returns:
        日志尾部文本；文件尚未创建时返回空内容及不存在状态。

    Raises:
        OSError: 除文件不存在外的读取错误继续上报。
    """
    try:
        with path.open("rb") as source:
            size = source.seek(0, 2)
            offset = max(0, size - MAX_LOG_TAIL_BYTES)
            source.seek(offset)
            data = source.read(MAX_LOG_TAIL_BYTES)
    except FileNotFoundError:
        return ConsoleLog(content="", exists=False)
    # UTF-8 字符可能跨越读取起点；解码后只展示文件末尾，避免整文件载入内存。
    lines = data.decode("utf-8", errors="replace").splitlines(keepends=True)
    if offset and len(lines) > 1:
        lines = lines[1:]
    return ConsoleLog(content="".join(lines[-line_limit:]), exists=True,
                      truncated=bool(offset or len(lines) > line_limit))
