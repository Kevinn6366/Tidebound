"""按账号保存模型凭据，不向前端回传密钥。"""

import json
import os
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class ModelCredentialInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    api_key: SecretStr = Field(min_length=8, max_length=512)


class ModelCredentialStore:
    """服务端账号隔离的硅基流动凭据存储。"""

    def __init__(self, root: Path) -> None:
        self.root = root

    def path(self, owner: str) -> Path:
        """将已鉴权的账号范围限制为 UUID 目录。

        Args:
            owner: 当前登录账号的服务端范围。

        Returns:
            当前账号专属的凭据文件路径。

        Raises:
            ValueError: 范围不是合法 UUID。
        """
        return self.root / UUID(owner).hex / 'settings' / 'siliconflow-key.json'

    def load(self, owner: str) -> SecretStr | None:
        """读取账号自己的凭据，文件不存在时返回空值。

        Args:
            owner: 当前登录账号的服务端范围。

        Returns:
            已保存的密钥；尚未设置时为 None。

        Raises:
            ValueError: 文件内容损坏。
            OSError: 文件不可读取。
        """
        try:
            return ModelCredentialInput.model_validate_json(self.path(owner).read_text()).api_key
        except FileNotFoundError:
            return None

    def save(self, owner: str, credential: ModelCredentialInput) -> None:
        """以仅所有者可读的临时文件原子替换账号凭据。

        Args:
            owner: 当前登录账号的服务端范围。
            credential: 已校验长度的硅基流动密钥。

        Raises:
            OSError: 写入或原子替换失败。
        """
        target = self.path(owner)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = target.with_name(f'.{uuid4().hex}.tmp')
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
                output.write(json.dumps({'api_key': credential.api_key.get_secret_value()}))
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    def delete(self, owner: str) -> None:
        """删除当前账号保存的密钥，不影响其他账号。

        Args:
            owner: 当前登录账号的服务端范围。

        Raises:
            OSError: 文件删除失败。
        """
        self.path(owner).unlink(missing_ok=True)
