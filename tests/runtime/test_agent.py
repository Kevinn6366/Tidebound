"""验证工具闭环、有限执行及会话提交边界。"""
import asyncio
import json
from pathlib import Path
from uuid import uuid4

import pytest

from backend.chat import session_view
from src.config import AgentSettings
from src.context.budget import select_messages
from src.errors import AgentError
from src.runtime.agent_loop import agent_loop
from src.runtime.session import ChatSession
from src.runtime.types import Message, ModelReply, RunRecord, ToolCall
from src.tools.registry import EmptyArguments, Tool, ToolRegistry, create_tools


def tool_reply(name: str = "get_current_time", arguments: str = "{}", finish: str = "tool_calls") -> ModelReply:
    return ModelReply(message=Message(role="assistant", tool_calls=[ToolCall(id="call-1", name=name, arguments=arguments)]), finish_reason=finish)


class ScriptedModel:
    def __init__(self, replies: list[ModelReply]) -> None:
        self.replies = replies
        self.inputs: list[list[Message]] = []

    async def complete(self, system: str, messages: list[Message], tools: list[dict[str, object]]) -> ModelReply:
        self.inputs.append(list(messages))
        return self.replies[min(len(self.inputs) - 1, len(self.replies) - 1)]


def final_reply() -> ModelReply:
    return ModelReply(message=Message(role="assistant", content="已读取时间。"), finish_reason="stop")


@pytest.mark.parametrize("name,args,error", [("get_current_time", "{}", None), ("missing", "{}", "unknown_tool"),
    ("get_current_time", '{"unexpected":1}', "invalid_arguments"), ("get_current_time", "bad-json", "invalid_arguments")])
def test_tool_results_feed_model(name: str, args: str, error: str | None) -> None:
    async def scenario() -> None:
        model = ScriptedModel([tool_reply(name, args), final_reply()])
        result = await agent_loop("atri", [], [Message(role="user", content="几点了")], model,
                                  AgentSettings(), asyncio.Event(), create_tools("Asia/Shanghai"))
        assert [m.role for m in result] == ["user", "assistant", "tool", "assistant"]
        tool = model.inputs[1][-1]
        assert tool.tool_call_id == "call-1"
        payload = json.loads(tool.content)
        if error:
            assert payload["error"] == error
        else:
            assert payload["timezone"] == "Asia/Shanghai"
            assert payload["timestamp"] > 0
    asyncio.run(scenario())


def test_new_registration_and_ordinary_exception() -> None:
    def broken(_: EmptyArguments) -> object:
        raise RuntimeError("private credential must not leak")
    registry = ToolRegistry([Tool("broken", "test", EmptyArguments, broken)])
    async def scenario() -> None:
        model = ScriptedModel([tool_reply("broken"), final_reply()])
        await agent_loop("atri", [], [Message(role="user", content="test")], model, AgentSettings(), asyncio.Event(), registry)
        assert "tool_execution_failed" in model.inputs[1][-1].content
        assert "private" not in model.inputs[1][-1].content
    asyncio.run(scenario())


@pytest.mark.parametrize("finish,limit,code", [("length", 4, "model_incomplete"), ("tool_calls", 2, "model_call_limit")])
def test_loop_bounds(finish: str, limit: int, code: str) -> None:
    async def scenario() -> None:
        model = ScriptedModel([tool_reply(finish=finish)])
        current = [Message(role="user", content="test")]
        with pytest.raises(AgentError) as failure:
            await agent_loop("atri", [], current, model, AgentSettings(max_model_calls=limit), asyncio.Event(), create_tools("UTC"))
        assert failure.value.code == code
        assert len(model.inputs) == (1 if finish == "length" else limit)
        if finish == "length":
            assert len(current) == 1  # 截断的工具不执行。
    asyncio.run(scenario())


class WaitingModel:
    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def complete(self, system: str, messages: list[Message], tools: list[dict[str, object]]) -> ModelReply:
        self.entered.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            # 模拟取消后仍到达的供应商回复，不能获得提交资格。
            await asyncio.sleep(0)
        return final_reply()


def test_session_stop_idempotency_isolation_restart(tmp_path: Path) -> None:
    async def scenario() -> None:
        settings = AgentSettings(base_url="http://model.test/v1", model="fixture", data_dir=tmp_path)
        model = WaitingModel()
        service = ChatSession(settings, model)
        owner, other, run_id = uuid4().hex, uuid4().hex, str(uuid4())
        service.start(owner, run_id, "hello")
        await model.entered.wait()
        assert service.start(owner, run_id, "hello").run_id == run_id
        for identity, content, code in [(run_id, "changed", "run_id_conflict"), (str(uuid4()), "new", "session_busy")]:
            with pytest.raises(AgentError) as failure:
                service.start(owner, identity, content)
            assert failure.value.code == code
        with pytest.raises(AgentError) as failure:
            service.get(other, run_id)
        assert failure.value.status == 404
        service.stop(owner, run_id)
        await service.active[owner].task
        assert service.get(owner, run_id).status == "stopped"
        assert session_view(service, owner).messages == []
        model = ScriptedModel([tool_reply(), final_reply()])
        service.model = model
        new_id = str(uuid4())
        service.start(owner, new_id, "几点了")
        service.stop(owner, run_id)  # 旧停止请求不影响新 Run。
        await service.active[owner].task
        assert service.get(owner, new_id).status == "completed"
        assert len(model.inputs[0]) == 1
        view = session_view(service, owner)
        assert len(view.messages) == 2
        assert view.tool_runs[0].tools[0].name == "get_current_time"
        assert view.tool_runs[0].tools[0].result
        restarted = ChatSession(settings, ScriptedModel([final_reply()]))
        assert len(session_view(restarted, owner).messages) == 2
        assert session_view(restarted, other).messages == []
        orphan = RunRecord(run_id=str(uuid4()), created_at="9999", user_content="interrupted")
        restarted.store.save(owner, orphan)
        assert restarted.get(owner, orphan.run_id).status == "interrupted"
        restarted.start(owner, str(uuid4()), "next")
        await restarted.active[owner].task
        assert [m.role for m in restarted.model.inputs[0]] == ["user", "assistant", "tool", "assistant", "user"]
    asyncio.run(scenario())


def test_timeout_retains_no_committed_turn(tmp_path: Path) -> None:
    class SlowModel:
        async def complete(self, system: str, messages: list[Message], tools: list[dict[str, object]]) -> ModelReply:
            await asyncio.sleep(10)
            return final_reply()
    async def scenario() -> None:
        service = ChatSession(AgentSettings(base_url="http://fixture", model="test", data_dir=tmp_path, timeout_seconds=0.02), SlowModel())
        owner, run_id = uuid4().hex, str(uuid4())
        service.start(owner, run_id, "hello")
        await service.active[owner].task
        assert service.get(owner, run_id).error_code == "run_timeout"
        assert not session_view(service, owner).messages
    asyncio.run(scenario())


def test_budget_keeps_complete_turns_and_mandatory_input() -> None:
    old = [Message(role="user", content="x" * 9000), Message(role="assistant", content="old")]
    recent = [Message(role="user", content="recent"), Message(role="assistant", content="yes")]
    current = [Message(role="user", content="now")]
    settings = AgentSettings(context_limit=4096, max_output_tokens=512)
    assert select_messages("atri", [old, recent], current, [], settings) == recent + current
    with pytest.raises(AgentError):
        select_messages("atri", [], old, [], settings)
