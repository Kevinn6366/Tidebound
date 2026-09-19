"""单 worker 开发服务的主模型渠道选择，只保存渠道标识。"""
import os
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

ChannelId = Literal['siliconflow', 'codex789']


class ChannelSelection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    channel: ChannelId = 'siliconflow'


class ModelChannelStore:
    def __init__(self, root: Path) -> None:
        self.path = root / 'settings' / 'model-channel.json'

    def load(self) -> ChannelSelection:
        """读取服务级选择，首次运行默认使用硅基流动。

        Returns:
            已校验的渠道标识。

        Raises:
            OSError: 文件无法读取。
            ValueError: 持久化内容损坏。
        """
        try:
            return ChannelSelection.model_validate_json(self.path.read_text())
        except FileNotFoundError:
            return ChannelSelection()

    def save(self, selection: ChannelSelection) -> None:
        """原子保存管理员选择，不写入模型凭据。

        Args:
            selection: 已验证为可用的目标渠道。

        Raises:
            OSError: 写入失败，原选择保持不变。
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f'.{uuid4().hex}.tmp')
        try:
            with temporary.open('x') as output:
                output.write(selection.model_dump_json())
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)
