"""验证工具闭环、有限执行及会话提交边界。"""
import asyncio
import json
from pathlib import Path
from uuid import uuid4

import pytest

from src.tidebound.config import AgentSettings
from src.tidebound.context.budget import select_messages
from src.tidebound.errors import AgentError
from src.tidebound.runtime.agent_loop import agent_loop
from src.tidebound.runtime.session import ChatSession
from src.tidebound.runtime.types import Message, ModelReply, RunRecord, ToolCall
from src.tidebound.tools.registry import EmptyArguments, ToolMap, create_tools
from webapp.chat_service import session_view


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


def test_system_safety_and_log_final_reply_only(tmp_path: Path) -> None:
    """验证常驻安全规则覆盖工具前后请求，过渡正文只留在执行审计中。

    Args:
        tmp_path: 隔离的执行记录目录。
    """
    from src.tidebound.config import ROOT
    from src.tidebound.prompting import load_prompt_bundles

    async def scenario() -> None:
        """执行带过渡正文的工具调用，再检查页面历史及重启恢复。"""
        systems: list[str] = []

        class CapturingModel(ScriptedModel):
            async def complete(self, system: str, messages: list[Message],
                               tools: list[dict[str, object]]) -> ModelReply:
                """记录实际 system 并返回预设响应。

                Args:
                    system: 主请求组装后的常驻与临时规则。
                    messages: 当前请求的对话及工具链。
                    tools: 当前允许的工具声明。

                Returns:
                    本次调用的受控模型响应。
                """
                systems.append(system)
                return await super().complete(system, messages, tools)

        transition = tool_reply()
        transition.message.content = "我来看看……"
        model = CapturingModel([transition, final_reply()])
        settings = AgentSettings(base_url="http://model.test/v1", model="fixture", data_dir=tmp_path)
        service = ChatSession(settings, model)
        owner, run_id = uuid4().hex, str(uuid4())
        service.start(owner, run_id, "现在几点？")
        await service.active[owner].task
        safety = load_prompt_bundles(ROOT / "prompts", ("chat.safety",)).content
        assert len(systems) == 2
        assert all(system.count(safety) == 1 for system in systems)
        assert "先获取当前时间再回答" not in systems[0]
        assert "先获取当前时间再回答" in systems[1]
        assert service.get(owner, run_id).messages[1].content == "我来看看……"
        for current in (service, ChatSession(settings, model)):
            view = session_view(current, owner)
            assert [message.content for message in view.messages] == ["现在几点？", "已读取时间。"]
            assert view.tool_runs[0].tools[0].result

    asyncio.run(scenario())


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
    registry: ToolMap = {"broken": {"description": "test", "arguments": EmptyArguments, "execute": broken}}
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


def test_injection_only_follows_tool_call_and_does_not_enter_history(tmp_path: Path) -> None:
    """验证调用后单次生效、重复触发以及跨轮不持久化。"""
    class InspectingModel:
        def __init__(self) -> None:
            self.systems: list[str] = []

        async def complete(self, system: str, messages: list[Message], tools: list[dict[str, object]]) -> ModelReply:
            """记录系统内容并模拟时间、未知、时间工具调用及最终回复。

            Args:
                system: 实际请求的系统内容。
                messages: 历史与本轮消息。
                tools: 可用工具声明。

            Returns:
                当前步骤的受控模型回复。
            """
            self.systems.append(system)
            step = len(self.systems)
            if step in (1, 3):
                return tool_reply()
            if step == 2:
                return tool_reply("unknown")
            return final_reply()

    async def scenario() -> None:
        model = InspectingModel()
        # 本用例验证多步注入，预算留足空间，避免角色文案变化触发压缩。
        service = ChatSession(AgentSettings(base_url="http://fixture", model="test", data_dir=tmp_path,
                                            context_limit=32768), model)
        owner, run_id = uuid4().hex, str(uuid4())
        service.start(owner, run_id, "现在几点")
        await service.active[owner].task
        record = service.get(owner, run_id)
        assert record.status == "completed"
        rule = "先获取当前时间再回答"
        assert [rule in system for system in model.systems] == [False, True, False, True]
        assert all(rule not in message.content for message in record.messages)
        service.start(owner, str(uuid4()), "下一轮")
        await service.active[owner].task
        assert rule not in model.systems[-1]

    asyncio.run(scenario())


def test_oversized_injection_blocks_next_model_request(tmp_path: Path) -> None:
    """工具后注入超限时应失败，不能绕过预算发送第二次请求。"""
    import shutil

    from src.tidebound.config import ROOT

    root = tmp_path / "prompts"
    shutil.copytree(ROOT / "prompts", root)
    (root / "master/tools.injection/tools.injection.timetools.md").write_text("规则" * 20000, encoding="utf-8")

    async def scenario() -> None:
        model = ScriptedModel([tool_reply(), final_reply()])
        with pytest.raises(AgentError) as failure:
            await agent_loop("atri", [], [Message(role="user", content="几点了")], model,
                             AgentSettings(prompts_dir=root), asyncio.Event(), create_tools("UTC"))
        assert failure.value.code == "context_budget_exceeded"
        assert len(model.inputs) == 1

    asyncio.run(scenario())


def test_context_reset_stops_old_run_and_survives_restart(tmp_path: Path) -> None:
    """重置后旧执行不能提交，新请求和重启均只读取新时间线。

    Args:
        tmp_path: 隔离执行与时间线状态文件。
    """
    async def scenario() -> None:
        settings = AgentSettings(base_url='http://fixture', model='fixture', data_dir=tmp_path)
        service = ChatSession(settings, ScriptedModel([final_reply()]))
        owner, other = uuid4().hex, uuid4().hex
        old_id = str(uuid4())
        service.start(owner, old_id, '旧事实')
        await service.active[owner].task
        service.start(other, str(uuid4()), '其他账号事实')
        await service.active[other].task
        waiting = WaitingModel()
        service.model = waiting
        active_id = str(uuid4())
        service.start(owner, active_id, '尚未完成')
        await waiting.entered.wait()
        await service.reset_context(owner)
        assert service.get(owner, active_id).status == 'stopped'
        assert session_view(service, owner).messages == []
        assert session_view(service, owner).active_run is None
        assert session_view(service, owner).context_usage.input_used is None
        assert len(session_view(service, other).messages) == 2
        assert len(service.store.list_runs(owner)) == 2  # 仅保留无正文墓碑用于拒绝旧请求。
        assert all(not r.messages and not r.user_content and r.companion_state is None
                   for r in service.store.list_runs(owner))
        with pytest.raises(AgentError) as error:
            service.start(owner, old_id, '旧事实')
        assert error.value.code == 'run_archived'
        model = ScriptedModel([final_reply()])
        restarted = ChatSession(settings, model)
        assert session_view(restarted, owner).messages == []
        restarted.start(owner, str(uuid4()), '全新输入')
        await restarted.active[owner].task
        assert [message.content for message in model.inputs[0]] == ['全新输入']
        assert len(session_view(restarted, owner).messages) == 2

    asyncio.run(scenario())


def test_worldview_run_snapshot_and_budget(tmp_path: Path) -> None:
    """验证世界观覆盖工具前后、下轮重载、欢迎入口及预算拒绝。

    Args:
        tmp_path: 隔离的提示词和运行记录目录。
    """
    import shutil

    from src.tidebound.config import ROOT
    from tests.runtime.test_meet import MeetModel

    root = tmp_path / "prompts"
    shutil.copytree(ROOT / "prompts", root)
    world = root / "master/world.worldview/world.worldview-zh.md"
    world.write_text("WORLD_FIRST", encoding="utf-8")

    async def scenario() -> None:
        """使用受控模型验证实际执行入口，不访问供应商。"""
        systems: list[str] = []

        class UpdatingModel(ScriptedModel):
            async def complete(self, system: str, messages: list[Message],
                               tools: list[dict[str, object]]) -> ModelReply:
                """记录 system 并模拟 Run 中途修改世界观。

                Args:
                    system: 当前请求的系统正文。
                    messages: 当前请求消息链。
                    tools: 可用工具声明。

                Returns:
                    预设工具调用或最终回复。
                """
                systems.append(system)
                world.write_text("WORLD_NEXT", encoding="utf-8")
                return await super().complete(system, messages, tools)

        model = UpdatingModel([tool_reply(), final_reply()])
        settings = AgentSettings(base_url="http://fixture", model="test", data_dir=tmp_path / "data",
                                 prompts_dir=root, context_limit=32768)
        service = ChatSession(settings, model)
        owner = uuid4().hex
        run = service.start(owner, str(uuid4()), "几点了")
        await service.active[owner].task
        assert run.status == "completed"
        assert len(systems) == 2
        assert all(system.count("WORLD_FIRST") == 1 and "WORLD_NEXT" not in system for system in systems)
        assert all("WORLD_FIRST" not in message.content for message in run.messages)
        service.start(owner, str(uuid4()), "你好")
        await service.active[owner].task
        assert systems[-1].count("WORLD_NEXT") == 1 and "WORLD_FIRST" not in systems[-1]
        await service.close()

        meet_model = MeetModel()
        service = ChatSession(settings, meet_model)
        other = uuid4().hex
        run = service.prepare_meet(other)
        await service.active[other].task
        assert run is not None and run.status == "completed"
        assert meet_model.inputs[0][0].count("WORLD_NEXT") == 1
        await service.close()

        world.write_text("世界观" * 20000, encoding="utf-8")
        blocked = ScriptedModel([final_reply()])
        service = ChatSession(settings, blocked)
        run = service.start(owner, str(uuid4()), "超限")
        await service.active[owner].task
        assert run.error_code == "context_budget_exceeded"
        assert not blocked.inputs
        await service.close()

    asyncio.run(scenario())


@pytest.mark.parametrize('prepared', [False, True])
def test_tail_injection_survives_other_tools_and_resets(prepared: bool) -> None:
    """搜索规则在整个请求末尾独立注入，参与预算但不污染历史或下一 Run。"""
    from src.tidebound.context.budget import measure_input
    from src.tidebound.context.compaction import PreparedContext
    from src.tidebound.prompting import load_tool_injections
    from src.tidebound.storage.model_requests import request_injection

    async def scenario() -> None:
        systems: list[str] = []
        audits: list[str | None] = []
        endings: list[Message] = []
        measured: list[int] = []

        class CapturingModel(ScriptedModel):
            async def complete(self, system: str, messages: list[Message],
                               tools: list[dict[str, object]]) -> ModelReply:
                """记录最终请求与注入审计。

                Args:
                    system: 完整系统提示词。
                    messages: 本次聊天材料。
                    tools: 可用工具声明。

                Returns:
                    预设工具或最终回复。
                """
                from src.tidebound.storage.model_requests import request_purpose
                if request_purpose.get() == 'tools.websearch.delivery':
                    return final_reply()
                systems.append(system)
                endings.append(messages[-1])
                audits.append(request_injection.get())
                measured.append(measure_input(system, messages, tools))
                return await super().complete(system, messages, tools)

        async def prepare(system: str, current: list[Message], tools: list[dict[str, object]]) -> PreparedContext:
            """模拟上下文层在工具规则之后追加其他系统规则。

            Args:
                system: 已含预算内工具规则的系统内容。
                current: 本轮必需材料。
                tools: 当前工具声明。

            Returns:
                附加规则后的上下文。
            """
            system += '\n\nOTHER_CONTEXT_RULE'
            return PreparedContext(system, list(current), measure_input(system, current, tools))

        settings = AgentSettings(context_limit=65536)
        tail = load_tool_injections(settings.prompts_dir, ('tools.injection.websearch',))
        registry = create_tools('UTC')
        registry['search_web'] = {'description': '搜索测试', 'arguments': EmptyArguments,
            'tail_injection': 'tools.injection.websearch', 'execute': lambda _: {'impression': '有限信息'}}
        model = CapturingModel([tool_reply('search_web'), tool_reply(), final_reply()])
        current = [Message(role='user', content='想了解近况')]
        usage = []
        await agent_loop('BASE', [], current, model, settings, asyncio.Event(), registry,
                         on_context=usage.append, prepare_context=prepare if prepared else None)
        assert tail not in systems[0]
        assert all(tail not in system for system in systems)
        assert all(message.role == 'system' and message.content == tail for message in endings[1:])
        assert all(tail in injection for injection in audits[1:])
        assert all(tail not in message.content for message in current)
        assert [item.input_used for item in usage] == measured
        await agent_loop('BASE', [], [Message(role='user', content='下一轮')], model,
                         settings, asyncio.Event(), registry, prepare_context=prepare if prepared else None)
        assert tail not in systems[-1]
        assert endings[-1].role != 'system'

    asyncio.run(scenario())
