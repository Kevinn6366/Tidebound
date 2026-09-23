"""开发账号的 MySQL 存储；身份查询不依赖 FastAPI。"""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Literal, Protocol

import pymysql
from pydantic import BaseModel, Field, SecretStr
from pymysql.cursors import DictCursor

from src.tidebound.errors import AgentError


class User(BaseModel):
    """可公开账号身份与仅服务端使用的存储归属。"""

    uid: str = Field(pattern=r"^uid-\d{8}$")
    username: str
    role: Literal["user", "admin"]
    scope: str = Field(exclude=True)


class StoredUser(User):
    salt: str
    password_hash: str


class UserStore(Protocol):
    """账号服务需要的最小存储入口。"""

    def list_users(self) -> list[StoredUser]: ...
    def add_user(self, user: StoredUser) -> None: ...


class MysqlSettings(BaseModel):
    host: str = "127.0.0.1"
    port: int = Field(default=53306, ge=1, le=65535)
    database: str = "tidebound"
    user: str = "tidebound"
    password: SecretStr = SecretStr("")

    @classmethod
    def from_env(cls) -> "MysqlSettings":
        """读取已由应用加载的环境变量。

        Returns:
            MySQL 连接参数，密码不参与模型字符串输出。
        """
        return cls.model_validate({name: os.environ[f"TIDEBOUND_MYSQL_{name.upper()}"]
                                   for name in cls.model_fields if f"TIDEBOUND_MYSQL_{name.upper()}" in os.environ})


class MysqlUserStore:
    """参数化访问独立 users 表，失败时明确报错，不回退到文件账号库。"""

    def __init__(self, settings: MysqlSettings) -> None:
        self.settings = settings
        self.initialized = False

    @contextmanager
    def _connection(self) -> Iterator[pymysql.Connection]:
        """取得短连接并在首次访问时建立账号表，离开时关闭连接。

        Yields:
            UTF-8 字典游标连接，事务由调用方显式提交。

        Raises:
            AgentError: 数据库不可用或约束冲突时返回不含连接凭据的错误。
        """
        if not self.settings.password.get_secret_value():
            raise AgentError("database_not_configured", "请先配置账号 MySQL 数据库。", 503)
        try:
            with pymysql.connect(host=self.settings.host, port=self.settings.port, user=self.settings.user,
                                 password=self.settings.password.get_secret_value(), database=self.settings.database,
                                 charset="utf8mb4", cursorclass=DictCursor, connect_timeout=5,
                                 read_timeout=5, write_timeout=5) as connection:
                if not self.initialized:
                    with connection.cursor() as cursor:
                        cursor.execute("""CREATE TABLE IF NOT EXISTS users (
                            uid CHAR(12) PRIMARY KEY,
                            username VARCHAR(64) NOT NULL,
                            username_key VARCHAR(192) NOT NULL UNIQUE,
                            role ENUM('user', 'admin') NOT NULL,
                            scope CHAR(32) NOT NULL UNIQUE,
                            salt CHAR(32) NOT NULL,
                            password_hash CHAR(64) NOT NULL,
                            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin""")
                    connection.commit()
                    self.initialized = True
                yield connection
        except pymysql.IntegrityError as error:
            raise AgentError("account_conflict", "账号名称或用户编号已存在。", 409) from error
        except pymysql.MySQLError as error:
            raise AgentError("database_unavailable", "账号数据库不可用，请检查本地 MySQL 服务。", 503) from error

    def list_users(self) -> list[StoredUser]:
        """读取账号身份与密码摘要，不向客户端直接返回。

        Returns:
            按 UID 排序的内部账号记录。

        Raises:
            AgentError: 数据库不可用。
        """
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT uid, username, role, scope, salt, password_hash FROM users ORDER BY uid")
            return [StoredUser.model_validate(row) for row in cursor.fetchall()]

    def add_user(self, user: StoredUser) -> None:
        """事务写入新账号，唯一键阻止重复分配 UID 和用户名。

        Args:
            user: 已由账号服务分配编号并派生密码摘要的新账号。

        Raises:
            AgentError: 数据库写入失败或唯一键冲突。
        """
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute("""INSERT INTO users (uid, username, username_key, role, scope, salt, password_hash)
                              VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                           (user.uid, user.username, user.username.casefold(), user.role, user.scope,
                            user.salt, user.password_hash))
            connection.commit()
