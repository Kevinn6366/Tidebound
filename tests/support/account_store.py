"""仅测试使用的文件账号存储替身，生产入口不能选择它。"""

import json
from pathlib import Path

from src.tidebound.storage.users import StoredUser


class FileUserStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def list_users(self) -> list[StoredUser]:
        """读取测试账号记录，供服务重建验证使用。

        Returns:
            已写入的测试账号。
        """
        if not self.path.exists():
            return []
        return [StoredUser.model_validate(item) for item in json.loads(self.path.read_text())]

    def add_user(self, user: StoredUser) -> None:
        """保存测试账号与内部 scope，模拟服务重建后继续读取。

        Args:
            user: 测试账号。
        """
        users = self.list_users() + [user]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps([item.model_dump() | {'scope': item.scope} for item in users]))
