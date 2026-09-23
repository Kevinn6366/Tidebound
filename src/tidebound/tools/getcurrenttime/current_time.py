"""当前时间工具：读取配置时区的真实时间。"""

from datetime import datetime
from zoneinfo import ZoneInfo


def get_current_time(timezone: str) -> dict[str, str | float]:
    """读取指定时区的真实当前时间。

    Args:
        timezone: 由后端配置的 IANA 时区名称。

    Returns:
        ISO 时间、时区和 Unix 秒数。

    Raises:
        ZoneInfoNotFoundError: 部署环境不支持所配置的时区。
    """
    now = datetime.now(ZoneInfo(timezone))
    return {"datetime": now.isoformat(), "timezone": timezone, "timestamp": now.timestamp()}
