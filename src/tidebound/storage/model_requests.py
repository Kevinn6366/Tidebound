"""保存模型边界的完整请求正文，供管理员 console 检查。"""

import os
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel

from src.tidebound.errors import AgentError

# asyncio 任务继承上下文，账号并发时不会串用 Run 标识。
request_run: ContextVar[tuple[str, str] | None] = ContextVar("request_run", default=None)
request_step: ContextVar[int] = ContextVar("request_step", default=0)
request_injection: ContextVar[str | None] = ContextVar("request_injection", default=None)
request_purpose: ContextVar[str] = ContextVar("request_purpose", default="chat")


class RequestSummary(BaseModel):
    request_id: str
    run_id: str
    owner: str
    step: int
    created_at: str
    model: str
    purpose: str = "chat"


class RequestSnapshot(RequestSummary):
    body: dict[str, object]
    injection: str | None = None


class RequestRunSummary(BaseModel):
    run_id: str
    owner: str
    created_at: str
    user_content: str
    requests: list[RequestSummary]


class ModelRequestStore:
    """独立于有效对话历史的本地请求快照。"""

    def __init__(self, root: Path) -> None:
        self.root = root / "model-requests"

    def save(self, body: dict[str, object]) -> RequestSnapshot | None:
        """在发起 HTTP 请求前原子保存正文，不接受请求头或凭据配置。

        Args:
            body: 即将传给模型 HTTP 客户端的完整 JSON 正文。

        Returns:
            已保存的快照；独立于会话的模型调用不生成 console 记录。

        Raises:
            OSError: 快照无法写入，此时不继续发送未记录的请求。
        """
        context = request_run.get()
        if context is None:
            return None
        owner, run_id = context
        snapshot = RequestSnapshot(request_id=uuid4().hex, run_id=run_id, owner=owner,
                                   step=request_step.get(), created_at=datetime.now(UTC).isoformat(),
                                   model=str(body["model"]), purpose=request_purpose.get(),
                                   body=body, injection=request_injection.get())
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.root / f"{snapshot.request_id}.json"
        temporary = target.with_suffix(".tmp")
        try:
            with temporary.open("x", encoding="utf-8") as output:
                output.write(snapshot.model_dump_json())
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        return snapshot

    def list_requests(self, offset: int = 0, limit: int = 50) -> list[RequestSummary]:
        """分页返回最新请求的摘要，不在轮询响应里重复传输完整正文。

        Args:
            offset: 从最新记录起跳过的条数。
            limit: 本页最多返回的条数。

        Returns:
            按文件写入时间倒序排列的请求摘要。

        Raises:
            OSError: 目录或文件读取失败。
            ValueError: 快照损坏。
        """
        paths = sorted(self.root.glob("*.json"), key=lambda path: (path.stat().st_mtime_ns, path.name), reverse=True)
        return [RequestSummary.model_validate(self.get(path.stem).model_dump()) for path in paths[offset:offset + limit]]

    def list_request_runs(self, offset: int = 0, limit: int = 50) -> list[RequestRunSummary]:
        """按完整对话分组再分页，同一 Run 的模型调用不会跨页拆开。

        Args:
            offset: 按对话开始时间倒序跳过的组数。
            limit: 每页最多返回的对话组数。

        Returns:
            含本轮用户输入和按调用序号排列的请求子菜单。

        Raises:
            OSError: 请求文件读取失败。
            ValueError: 快照损坏。
        """
        groups: dict[tuple[str, str], list[RequestSnapshot]] = {}
        for path in self.root.glob("*.json"):
            snapshot = self.get(path.stem)
            groups.setdefault((snapshot.owner, snapshot.run_id), []).append(snapshot)
        result: list[RequestRunSummary] = []
        for (owner, run_id), snapshots in groups.items():
            snapshots.sort(key=lambda item: (item.created_at, item.request_id))
            first = snapshots[0]
            messages = first.body.get("messages", [])
            user_content = ""
            if isinstance(messages, list):
                for message in reversed(messages):
                    if isinstance(message, dict) and message.get("role") == "user":
                        content = message.get("content")
                        user_content = content if isinstance(content, str) else ""
                        break
            result.append(RequestRunSummary(
                run_id=run_id, owner=owner, created_at=first.created_at, user_content=user_content,
                requests=[RequestSummary.model_validate(item.model_dump()) for item in snapshots],
            ))
        result.sort(key=lambda item: (item.created_at, item.owner, item.run_id), reverse=True)
        return result[offset:offset + limit]

    def get(self, request_id: str) -> RequestSnapshot:
        """读取指定请求的未截断快照。

        Args:
            request_id: 请求 UUID，不能用于指定任意路径。

        Returns:
            包含完整模型请求正文的快照。

        Raises:
            AgentError: 请求快照不存在。
            OSError: 文件不可读。
            ValueError: 标识非法或文件损坏。
        """
        try:
            return RequestSnapshot.model_validate_json((self.root / f"{UUID(request_id).hex}.json").read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise AgentError("model_request_not_found", "模型请求记录不存在。", 404) from error
