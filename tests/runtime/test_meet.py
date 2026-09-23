"""验证欢迎触发、持久化去重、上下文、停止及账号隔离。"""

import asyncio
import json
from datetime import UTC, datetime, timedelta, tzinfo
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from src.tidebound.config import AgentSettings
from src.tidebound.errors import AgentError
from src.tidebound.llm import wire_messages
from src.tidebound.prompting import load_prompt_bundles
from src.tidebound.runtime.session import ChatSession
from src.tidebound.runtime.types import Message, ModelReply, RunRecord, ToolCall
from src.tidebound.storage.model_requests import request_injection, request_purpose, request_step
from tests.support.account_store import FileUserStore
from webapp.chat_service import session_view
from webapp.config import WebSettings
from webapp.main import create_app


class MeetModel:
    """捕获实际工作流输入，支持延迟、失败与取消后迟到返回。"""

    def __init__(self, *, wait: bool = False, fail: bool = False) -> None:
        self.inputs: list[tuple[str, list[Message], list[dict[str, object]], str]] = []
        self.wait = wait
        self.fail = fail
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def complete(self, system: str, messages: list[Message], tools: list[dict[str, object]]) -> ModelReply:
        """记录调用并返回可控正文。

        Args:
            system: 实际组装的全部系统规则。
            messages: 本次选取的历史和事件材料。
            tools: 本次获准的工具，欢迎只开放时间查询。

        Returns:
            完整问候或被测试故意构造的无效正文。
        """
        self.inputs.append((system, list(messages), tools, request_purpose.get()))
        self.entered.set()
        if self.wait:
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                # 模拟无法取消的供应商迟到结果，runtime 仍必须拒绝提交。
                return ModelReply(message=Message(role="assistant", content="迟到问候"), finish_reason="stop")
        return ModelReply(message=Message(role="assistant", content="" if self.fail else "你来啦，今天想聊些什么？"),
                          finish_reason="stop")


def service_at(root: Path, model: MeetModel) -> ChatSession:
    """创建真实提示词、隔离存储和受控模型的会话。

    Args:
        root: 当前测试的运行目录。
        model: 可控的欢迎和普通聊天模型。

    Returns:
        不访问网络或真实账号的 runtime。
    """
    return ChatSession(AgentSettings(base_url="http://fixture", model="fixture", data_dir=root), model)


def test_first_meet_commits_without_view_and_feeds_next_chat(tmp_path: Path) -> None:
    """后台独立完成，角色注入正确，欢迎只有 assistant 且进入后续上下文。

    Args:
        tmp_path: 隔离的历史目录。
    """
    async def scenario() -> None:
        model = MeetModel(wait=True)
        service = service_at(tmp_path, model)
        owner = uuid4().hex
        run = service.prepare_meet(owner)
        assert run is not None
        task = service.active[owner].task
        assert service.prepare_meet(owner).run_id == run.run_id
        await asyncio.wait_for(model.entered.wait(), 2)
        assert session_view(service, owner).messages == []
        assert run.preview == ""
        with pytest.raises(AgentError, match="尚未结束"):
            service.start(owner, str(uuid4()), "不允许并发")
        model.release.set()
        await task
        assert run.status == "completed"
        assert [item.role for item in run.messages] == ["assistant"]
        assert run.completed_at == run.messages[0].created_at
        system, messages, tools, purpose = model.inputs[0]
        for name in ("chat.character", "chat.safety", "chat.meet"):
            assert load_prompt_bundles(service.settings.prompts_dir, (name,)).content in system
        assert tools[0]["function"]["name"] == "use_tool" and purpose == "chat.meet"
        assert "get_current_time" in tools[0]["function"]["description"]
        event = json.loads(messages[-1].content)
        assert event["event"] == "first_meet"
        assert "current_time" not in event and "timezone" not in event
        assert len(session_view(service, owner).messages) == 1
        restarted = service_at(tmp_path, model)
        assert restarted.prepare_meet(owner).run_id == run.run_id
        assert restarted.prepare_meet(owner, retry=True).run_id == run.run_id
        restarted.start(owner, str(uuid4()), "你好")
        await restarted.active[owner].task
        assert model.inputs[-1][1][0].content == run.messages[0].content
        assert "chat.meet" != model.inputs[-1][3]
        assert load_prompt_bundles(service.settings.prompts_dir, ("chat.meet",)).content not in model.inputs[-1][0]
        assert [m.role for m in session_view(restarted, owner).messages] == ["assistant", "user", "assistant"]
        assert restarted.prepare_meet(owner) is None
        await restarted.close()
        await service.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("minutes,expected", [(29, False), (30, False), (31, True)])
def test_return_boundary_and_no_periodic_duplicate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                   minutes: int, expected: bool) -> None:
    """精确检查 30 分钟边界，未过期问候不因再次进入而重复。

    Args:
        tmp_path: 隔离历史目录。
        monkeypatch: 冻结服务端时钟。
        minutes: 距上轮完成的分钟数。
        expected: 此次进入是否应生成问候。
    """
    from src.tidebound.runtime import session

    class Clock(datetime):
        current = datetime(2026, 9, 17, 12, tzinfo=UTC)

        @classmethod
        def now(cls, tz: object = None) -> datetime:
            return cls.current

    monkeypatch.setattr(session, "datetime", Clock)

    async def scenario() -> None:
        model = MeetModel()
        service = service_at(tmp_path, model)
        owner = uuid4().hex
        at = (Clock.current - timedelta(minutes=minutes)).isoformat()
        service.store.save(owner, RunRecord(run_id=str(uuid4()), created_at=at, completed_at=at,
            status="completed", user_content="周末去看海", messages=[
                Message(role="user", content="周末去看海", created_at=at),
                Message(role="assistant", content="好呀", created_at=at)]))
        greeting = service.prepare_meet(owner)
        assert (greeting is not None) == expected
        if greeting:
            await service.active[owner].task
            assert greeting.status == "completed"
            assert json.loads(model.inputs[0][1][-1].content)["event"] == "return_meet"
            assert model.inputs[0][1][0].content == "周末去看海"
            Clock.current += timedelta(minutes=59)
            assert service.prepare_meet(owner).run_id == greeting.run_id
            assert len(model.inputs) == 1
            service.start(owner, str(uuid4()), "我回来啦")
            await service.active[owner].task
            Clock.current += timedelta(minutes=31)
            next_meet = service.prepare_meet(owner)
            assert next_meet.run_id != greeting.run_id
            await service.active[owner].task
        await service.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("seconds,expired", [(3599, False), (3600, True), (3601, True)])
def test_completed_meet_expires_only_on_authenticated_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, seconds: int, expired: bool,
) -> None:
    """成功欢迎按完成时间过期，查询和重启不触发生成，再次进入才检查。

    Args:
        tmp_path: 隔离运行数据目录。
        monkeypatch: 控制欢迎入口与执行使用的服务端时钟。
        seconds: 距离旧欢迎完成的秒数。
        expired: 再次进入是否应创建新的欢迎。
    """
    from src.tidebound.runtime import session

    class Clock(datetime):
        current = datetime(2026, 9, 22, 4, tzinfo=UTC)

        @classmethod
        def now(cls, tz: tzinfo | None = None) -> datetime:
            return cls.current.astimezone(tz)

    monkeypatch.setattr(session, "datetime", Clock)

    async def scenario() -> None:
        model = MeetModel(wait=True)
        service = service_at(tmp_path, model)
        owner = uuid4().hex
        completed = Clock.current - timedelta(seconds=seconds)
        previous = RunRecord(
            run_id=str(uuid4()), created_at=(completed - timedelta(minutes=5)).isoformat(),
            completed_at=completed.isoformat(), kind="meet", status="completed", user_content="",
            messages=[Message(role="assistant", content="旧问候")],
        )
        service.store.save(owner, previous)
        await service.close()
        service = service_at(tmp_path, model)
        assert session_view(service, owner).meet_run.run_id == previous.run_id
        assert not service.active and model.inputs == []
        run = service.prepare_meet(owner)
        assert (run.run_id != previous.run_id) == expired
        if expired:
            assert service.prepare_meet(owner).run_id == run.run_id
            await asyncio.wait_for(model.entered.wait(), 2)
            event = json.loads(model.inputs[0][1][-1].content)
            assert "current_time" not in event
            model.release.set()
            await service.active[owner].task
            assert run.status == "completed"
            assert service.prepare_meet(owner).run_id == run.run_id
            assert len(session_view(service, owner).messages) == 2
        else:
            assert model.inputs == []
        await service.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("tool_name,arguments,error", [
    ("get_current_time", "{}", None),
    ("get_current_time", '{"timezone":"UTC"}', "invalid_arguments"),
    ("get_weather", "{}", "unknown_tool"),
])
def test_meet_model_selects_time_tool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    tool_name: str, arguments: str, error: str | None,
) -> None:
    """时间仅在模型提出调用后读取，工具结果和规则不污染正式对话。

    Args:
        tmp_path: 隔离运行数据目录。
        monkeypatch: 监测时间工具，确认没有提前读取。
        tool_name: 模型选择的实际能力。
        arguments: 模型给出的业务参数 JSON。
        error: 应由工具边界返回的错误码，空值代表成功。
    """
    from src.tidebound.tools import registry

    queried_zones: list[str] = []
    actual_time = registry.get_current_time

    def tracked_time(timezone: str) -> dict[str, str | float]:
        """记录工具调用所使用的服务端时区。

        Args:
            timezone: 注册表绑定的时区。

        Returns:
            真实时间工具的结果。
        """
        queried_zones.append(timezone)
        return actual_time(timezone)

    monkeypatch.setattr(registry, "get_current_time", tracked_time)

    class ToolModel(MeetModel):
        async def complete(self, system: str, messages: list[Message], tools: list[dict[str, object]]) -> ModelReply:
            """先由模型提出调用，再验证回填结果并生成问候。

            Args:
                system: 当前请求的完整系统规则。
                messages: 事件、调用及工具返回消息。
                tools: 本轮开放的时间能力声明。

            Returns:
                第一次返回工具调用，第二次返回最终问候。
            """
            self.inputs.append((system, list(messages), tools, request_purpose.get()))
            assert request_purpose.get() == "chat.meet"
            assert request_step.get() == len(self.inputs)
            assert load_prompt_bundles(service.settings.prompts_dir, ("chat.meet",)).content in request_injection.get()
            if len(self.inputs) == 1:
                assert queried_zones == []
                assert set(json.loads(messages[-1].content)) == {"event", "last_dialogue_at"}
                assert time_rules not in system
                assert "get_weather" not in tools[0]["function"]["description"]
                return ModelReply(message=Message(role="assistant", content="查询时间的过渡正文", tool_calls=[
                    ToolCall(id="meet-time", name="use_tool", arguments=json.dumps({
                        "name": tool_name, "arguments": arguments,
                    })),
                ]), finish_reason="tool_calls")
            result = json.loads(messages[-1].content)
            assert messages[-1].role == "tool" and messages[-1].tool_call_id == "meet-time"
            if error:
                assert result["error"] == error and queried_zones == []
            else:
                assert queried_zones == ["Asia/Shanghai"]
                assert started_at <= datetime.fromisoformat(result["datetime"]) <= datetime.now(UTC)
            assert (time_rules in system) == (tool_name == "get_current_time")
            return ModelReply(message=Message(role="assistant", content="你来啦。"), finish_reason="stop")

    model = ToolModel()
    service = service_at(tmp_path, model)
    time_rules = load_prompt_bundles(service.settings.prompts_dir, ("tools.injection.timetools",)).content
    started_at = datetime.now(UTC)

    async def scenario() -> None:
        owner = uuid4().hex
        run = service.prepare_meet(owner)
        await service.active[owner].task
        assert run.status == "completed", run.error
        assert len(model.inputs) == 2
        assert [(message.role, message.content) for message in run.messages] == [("assistant", "你来啦。")]
        assert run.preview != "查询时间的过渡正文"
        await service.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("action", ["stop", "reset", "timeout"])
def test_late_greeting_never_commits(tmp_path: Path, action: str) -> None:
    """停止、清空及超时不能被供应商迟到返回恢复为成功。

    Args:
        tmp_path: 隔离执行目录。
        action: 本次测试撤销执行资格的方式。
    """
    async def scenario() -> None:
        model = MeetModel(wait=True)
        service = service_at(tmp_path, model)
        if action == "timeout":
            service.settings.meet_timeout_seconds = 0.03
        owner = uuid4().hex
        run = service.prepare_meet(owner)
        task = service.active[owner].task
        await asyncio.wait_for(model.entered.wait(), 2)
        if action == "reset":
            await asyncio.wait_for(service.reset_context(owner), 2)
        elif action == "stop":
            service.stop(owner, run.run_id)
        await asyncio.wait_for(task, 2)
        assert run.status != "completed"
        assert session_view(service, owner).messages == []
        assert owner not in service.active
        if action == "stop":
            assert service.prepare_meet(owner).run_id == run.run_id
        await service.close()
    asyncio.run(scenario())


def test_failed_and_interrupted_meet_require_explicit_retry(tmp_path: Path) -> None:
    """失败与重启中断不会自动循环重试，用户仍能主动重试或聊天。

    Args:
        tmp_path: 隔离运行目录。
    """
    async def scenario() -> None:
        model = MeetModel(fail=True)
        service = service_at(tmp_path, model)
        owner = uuid4().hex
        run = service.prepare_meet(owner)
        await service.active[owner].task
        assert run.status == "failed"
        assert service.prepare_meet(owner).run_id == run.run_id
        assert len(model.inputs) == 1
        model.fail = False
        retry = service.prepare_meet(owner, retry=True)
        await service.active[owner].task
        assert retry.status == "completed"
        other = uuid4().hex
        abandoned = RunRecord(run_id=str(uuid4()), created_at=datetime.now(UTC).isoformat(), kind="meet", user_content="")
        service.store.save(other, abandoned)
        assert service.prepare_meet(other).status == "interrupted"
        service.start(other, str(uuid4()), "直接开始聊天")
        await service.active[other].task
        assert len(session_view(service, other).messages) == 2
        await service.close()
    asyncio.run(scenario())


def test_meet_api_isolation_sse_and_legacy_times(tmp_path: Path) -> None:
    """HTTP 入口归属不可伪造，完成 SSE 不含假用户消息，旧时间保留估算语义。

    Args:
        tmp_path: 独立账号、界面与运行数据目录。
    """
    async def scenario() -> None:
        model = MeetModel(wait=True)
        settings = AgentSettings(base_url="http://fixture", model="fixture", data_dir=tmp_path / "runs")
        app = create_app(WebSettings(ui_data_dir=tmp_path / "ui"), settings, model,
                         FileUserStore(tmp_path / "users.json"))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            assert not app.state.chat.active
            assert model.inputs == []
            assert (await client.post("/api/chat/meet")).status_code == 401
            assert model.inputs == []
            assert not app.state.chat.active
            assert (await client.post("/api/auth/setup", json={"username": "admin", "password": "password123"})).status_code == 201
            assert (await client.get("/api/chat/session")).json()["meet_run"] is None
            assert model.inputs == []
            response = await client.post("/api/chat/meet")
            assert response.status_code == 200
            run_id = response.json()["active_run"]["run_id"]
            assert response.json()["messages"] == []
            assert (await client.post("/api/chat/meet")).json()["active_run"]["run_id"] == run_id
            await model.entered.wait()
            model.release.set()
            await asyncio.gather(*(item.task for item in app.state.chat.active.values()))
            stream = await client.get(f"/api/chat/runs/{run_id}/events")
            payload = json.loads(stream.text.removeprefix("data: ").strip())
            assert payload["status"] == "completed" and payload["kind"] == "meet"
            assert payload["user_content"] == ""
            view = (await client.get("/api/chat/session")).json()
            assert len(view["messages"]) == 1 and view["messages"][0]["created_at"] is None
            display = await client.post(f"/api/chat/runs/{run_id}/display", json={"revision": payload["display_revision"]})
            assert display.status_code == 200
            shown = display.json()["display_started_at"]
            assert shown is not None
            assert (await client.post(f"/api/chat/runs/{run_id}/display", json={"revision": payload["display_revision"]})).json()["display_started_at"] == shown
            assert (await client.get("/api/chat/session")).json()["messages"][0]["created_at"] == shown
            await client.post("/api/auth/logout")
            await client.post("/api/auth/register", json={"username": "other", "password": "password123"})
            assert (await client.get(f"/api/chat/runs/{run_id}")).status_code == 404
            assert (await client.post(f"/api/chat/runs/{run_id}/display", json={"revision": 0})).status_code == 404
            assert (await client.get("/api/chat/session")).json()["messages"] == []
            assert (await client.post("/api/chat/meet/test")).status_code == 403
        owner = uuid4().hex
        legacy = RunRecord(run_id=str(uuid4()), created_at="2026-09-01T00:00:00Z", status="completed",
            user_content="旧对话", messages=[Message(role="user", content="旧对话"), Message(role="assistant", content="旧回复")])
        app.state.chat.store.save(owner, legacy)
        displayed = session_view(app.state.chat, owner).messages
        assert displayed[-1].time_estimated and displayed[-1].created_at == legacy.created_at
        stamped = Message(role="user", content="正文", created_at="2026-09-17T01:00:00Z")
        assert wire_messages("system", [stamped])[1]["content"] == "正文"
        assert "message_time" not in json.dumps(wire_messages("system", [stamped]))
        assert stamped.content == "正文"
        await app.state.chat.close()
    asyncio.run(scenario())


def test_manual_meet_bypasses_cooldown_but_preserves_execution_boundaries(tmp_path: Path) -> None:
    """管理员测试可重复生成，仍拒绝非 dev、普通执行及重置竞争。

    Args:
        tmp_path: 独立历史和模型配置目录。
    """
    async def scenario() -> None:
        model = MeetModel()
        service = service_at(tmp_path, model)
        # 连续手动问候验证执行边界，不让真实角色文案长度触发预算分支。
        service.settings.context_limit = 32768
        owner = uuid4().hex
        first = service.prepare_meet(owner)
        await service.active[owner].task
        second = service.prepare_meet(owner, trigger="manual")
        assert second.run_id != first.run_id
        assert service.prepare_meet(owner, trigger="manual").run_id == second.run_id
        await service.active[owner].task
        assert len(session_view(service, owner).messages) == 2
        assert service.prepare_meet(owner).run_id == second.run_id
        service.start(owner, str(uuid4()), "正在聊天")
        with pytest.raises(AgentError, match="尚未结束"):
            service.prepare_meet(owner, trigger="manual")
        await service.active[owner].task
        third = service.prepare_meet(owner, trigger="manual")
        await service.active[owner].task
        assert third.status == "completed"
        service.resetting.add(owner)
        with pytest.raises(AgentError, match="清空上下文"):
            service.prepare_meet(owner, trigger="manual")
        service.resetting.clear()
        service.settings.mode = "prod"
        with pytest.raises(AgentError, match="开发环境"):
            service.prepare_meet(owner, trigger="manual")
        await service.close()
    asyncio.run(scenario())


def test_display_time_tracks_current_preview_and_survives_restart(tmp_path: Path) -> None:
    """最终正文以展示开始计时，工具过渡版本及停止后的确认不能污染 Log。

    Args:
        tmp_path: 隔离记录目录。
    """
    from src.tidebound.runtime.preview import preview_sink

    class PreviewModel(MeetModel):
        async def complete(self, system: str, messages: list[Message], tools: list[dict[str, object]]) -> ModelReply:
            """提供可控的预览版本并等待测试放行。

            Args:
                system: 本次系统规则。
                messages: 本次对话输入。
                tools: 普通聊天的工具定义。

            Returns:
                正常结束的最终正文。
            """
            self.sink = preview_sink.get()
            self.sink("过渡正文")
            self.entered.set()
            await self.release.wait()
            return ModelReply(message=Message(role="assistant", content="最终正文"), finish_reason="stop")

    async def scenario() -> None:
        model = PreviewModel()
        service = service_at(tmp_path, model)
        owner = uuid4().hex
        run = service.start(owner, str(uuid4()), "问题")
        task = service.active[owner].task
        await model.entered.wait()
        old_revision = run.display_revision
        service.record_display_start(owner, run.run_id, old_revision)
        assert run.display_started_at
        model.sink("")
        assert run.display_started_at is None
        with pytest.raises(AgentError, match="失效"):
            service.record_display_start(owner, run.run_id, old_revision)
        model.sink("最终正文")
        service.record_display_start(owner, run.run_id, run.display_revision)
        displayed = run.display_started_at
        model.release.set()
        await task
        assert displayed < run.completed_at
        assert session_view(service, owner).messages[-1].created_at == displayed
        restarted = service_at(tmp_path, model)
        assert restarted.record_display_start(owner, run.run_id, run.display_revision).display_started_at == displayed
        await restarted.reset_context(owner)
        with pytest.raises(AgentError, match="失效"):
            restarted.record_display_start(owner, run.run_id, run.display_revision)
        await restarted.close()
        await service.close()
    asyncio.run(scenario())
