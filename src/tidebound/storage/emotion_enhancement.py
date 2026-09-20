"""按账号保存开发环境的云端情感增强开关，不持久化模型凭据。"""

import os
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict


class EmotionSetting(BaseModel):
    """当前账号下次回复是否使用云端情感润色。"""

    model_config = ConfigDict(extra="forbid", strict=True)
    enabled: bool = False


class EmotionEnhancementStore:
    """独立于对话时间线保存账号的情感增强选择。"""

    def __init__(self, root: Path) -> None:
        self.root = root

    def load(self, owner: str) -> EmotionSetting:
        """读取账号开关，首次使用时保持关闭。

        Args:
            owner: 经服务端鉴权确定的账号内部 UUID 范围。

        Returns:
            严格校验后的账号开关，不包含连接地址或凭据。

        Raises:
            OSError: 设置文件无法读取。
            ValueError: 账号范围或持久化内容不合法。
        """
        path = self.root / UUID(owner).hex / "state" / "emotion-enhancement.json"
        try:
            return EmotionSetting.model_validate_json(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return EmotionSetting()

    def save(self, owner: str, setting: EmotionSetting) -> None:
        """原子保存账号开关，失败时保留之前的完整设置。

        Args:
            owner: 经服务端鉴权确定的账号内部 UUID 范围。
            setting: 已校验的情感增强启停选择。

        Raises:
            OSError: 创建目录、写入或替换文件失败。
            ValueError: 账号范围不合法。
        """
        directory = self.root / UUID(owner).hex / "state"
        directory.mkdir(parents=True, exist_ok=True)
        temporary = directory / f".{uuid4().hex}.tmp"
        try:
            with temporary.open("x", encoding="utf-8") as output:
                output.write(setting.model_dump_json())
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, directory / "emotion-enhancement.json")
        finally:
            temporary.unlink(missing_ok=True)
