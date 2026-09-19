"""单 worker 开发服务的账号数据库访问、密码验证和会话管理。"""

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from src.tidebound.errors import AgentError
from src.tidebound.storage.users import StoredUser, User, UserStore

SESSION_SECONDS = 86400
PASSWORD_ITERATIONS = 600_000


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=2, max_length=64, pattern=r"^\S(?:.*\S)?$")
    password: str = Field(min_length=8, max_length=256)


@dataclass
class Session:
    uid: str
    expires_at: float
    debug_login: bool = False


def hash_password(password: str, salt: str) -> str:
    """使用独立随机盐派生密码摘要。

    Args:
        password: 用户提交的原始密码，不保存或记录。
        salt: 当前账号的十六进制随机盐。

    Returns:
        PBKDF2 SHA-256 摘要。
    """
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), PASSWORD_ITERATIONS).hex()


class DebugLoginState(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    enabled: bool = False


class AuthService:
    """账号保存在 MySQL；随机会话仅驻留内存，重启后重新登录。"""

    def __init__(self, store: UserStore, *, development: bool = False,
                 debug_state_path: Path | None = None) -> None:
        """加载账号服务与开发登录偏好，生产模式不读取免密码开关。

        Args:
            store: 账号存储入口。
            development: 是否为可启用调试的开发服务。
            debug_state_path: 服务端固定的调试开关文件，省略时仅保存在内存。

        Raises:
            OSError: 已有开关文件无法读取。
            ValueError: 开关文件结构损坏。
        """
        self.development = development
        self.debug_state_path = debug_state_path
        self.passwordless_debug = False
        if development and debug_state_path is not None:
            try:
                self.passwordless_debug = DebugLoginState.model_validate_json(debug_state_path.read_text()).enabled
            except FileNotFoundError:
                pass  # 首次启动仍默认关闭；损坏配置不会静默开启。
        self.store = store
        self.lock = RLock()
        self.sessions: dict[str, Session] = {}

    @property
    def setup_required(self) -> bool:
        with self.lock:
            return not self.store.list_users()

    def create_user(self, credentials: Credentials, *, setup: bool = False) -> User:
        """原子分配连续 UID；仅空账号库的初始化请求可创建管理员。

        Args:
            credentials: 已校验的用户名和密码。
            setup: 是否为首次管理员初始化，不能用于提升已有账号权限。

        Returns:
            新账号的公开身份和内部存储归属。

        Raises:
            AgentError: 初始化状态冲突、用户名重复或数据库写入失败。
        """
        with self.lock:
            users = self.store.list_users()
            if setup != (not users):
                raise AgentError("setup_conflict", "请先初始化管理员，或使用登录/注册入口。", 409)
            if any(user.username.casefold() == credentials.username.casefold() for user in users):
                raise AgentError("username_exists", "用户名已存在。", 409)
            salt = secrets.token_hex(16)
            user = StoredUser(uid=f"uid-{len(users) + 1:08d}", username=credentials.username,
                              role="admin" if setup else "user", scope=uuid4().hex, salt=salt,
                              password_hash=hash_password(credentials.password, salt))
            self.store.add_user(user)
            return User.model_validate(user.model_dump() | {"scope": user.scope})

    def login(self, credentials: Credentials) -> User:
        """校验密码并返回账号，失败信息不区分账号是否存在。

        Args:
            credentials: 用户名与密码。

        Returns:
            已验证的账号身份。

        Raises:
            AgentError: 用户名或密码不正确。
        """
        with self.lock:
            user = next((item for item in self.store.list_users()
                         if item.username.casefold() == credentials.username.casefold()), None)
            digest = hash_password(credentials.password, user.salt if user else "00" * 16)
            if user is None or not hmac.compare_digest(digest, user.password_hash):
                raise AgentError("invalid_credentials", "用户名或密码不正确。", 401)
            return User.model_validate(user.model_dump() | {"scope": user.scope})

    def set_passwordless_debug(self, enabled: bool) -> bool:
        """持久化开发免密码开关，关闭时撤销免密码签发的会话。

        Args:
            enabled: 管理员选择的调试状态，开发服务重启后保持。

        Returns:
            当前启用状态。

        Raises:
            AgentError: 非开发服务不可开启。
            OSError: 开关持久化失败，原状态保持不变。
        """
        with self.lock:
            if not self.development:
                raise AgentError('dev_only', '仅开发模式支持免密码调试。', 403)
            if self.debug_state_path is not None:
                self.debug_state_path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.debug_state_path.with_name(f'.{uuid4().hex}.tmp')
                try:
                    temporary.write_text(DebugLoginState(enabled=enabled).model_dump_json())
                    temporary.replace(self.debug_state_path)
                finally:
                    temporary.unlink(missing_ok=True)
            self.passwordless_debug = enabled
            if not enabled:
                self.sessions = {key: value for key, value in self.sessions.items() if not value.debug_login}
            return enabled

    def debug_login(self, username: str) -> User:
        """开发调试按用户名登录，不存在时创建普通账号。

        Args:
            username: 已通过接口格式校验的用户名。

        Returns:
            已有账号或新建普通账号。

        Raises:
            AgentError: 开关关闭、非开发模式或尚未初始化管理员。
        """
        with self.lock:
            if not self.development or not self.passwordless_debug:
                raise AgentError('debug_login_disabled', '免密码调试未开启。', 403)
            if self.setup_required:
                raise AgentError('setup_required', '请先初始化管理员。', 409)
            user = next((item for item in self.store.list_users()
                         if item.username.casefold() == username.casefold()), None)
            if user is None:
                return self.create_user(Credentials(username=username, password=secrets.token_urlsafe(32)))
            return User.model_validate(user.model_dump() | {'scope': user.scope})

    def issue_session(self, user: User, old_token: str | None, *, debug_login: bool = False) -> str:
        """轮换随机会话并清理过期项。

        Args:
            user: 刚完成验证的账号。
            old_token: 浏览器原有会话，存在时作废。
            debug_login: 是否由免密码调试入口签发，关闭开关时撤销。

        Returns:
            只交给 HttpOnly Cookie 的随机会话令牌。
        """
        with self.lock:
            if debug_login and (not self.development or not self.passwordless_debug):
                raise AgentError("debug_login_disabled", "免密码调试未开启。", 403)
            self.logout(old_token)
            now = time.time()
            self.sessions = {key: value for key, value in self.sessions.items() if value.expires_at > now}
            token = secrets.token_urlsafe(32)
            self.sessions[token] = Session(user.uid, now + SESSION_SECONDS, debug_login)
            return token

    def resolve(self, token: str | None) -> User | None:
        """解析有效会话，每次从服务端账号记录读取角色。

        Args:
            token: 请求 Cookie 中的随机会话令牌。

        Returns:
            已登录身份；无效或过期时返回 None。
        """
        with self.lock:
            session = self.sessions.get(token or "")
            if session is None or session.expires_at <= time.time():
                self.logout(token)
                return None
            user = next((item for item in self.store.list_users() if item.uid == session.uid), None)
            return User.model_validate(user.model_dump() | {"scope": user.scope}) if user else None

    def logout(self, token: str | None) -> None:
        """撤销指定浏览器会话。

        Args:
            token: 待撤销的会话令牌；缺失时无需操作。
        """
        with self.lock:
            self.sessions.pop(token or "", None)
