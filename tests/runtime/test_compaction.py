"""验证节点顺序、滚动覆盖、静默并发和时间线提交边界。"""

import asyncio
import json
import shutil
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from src.tidebound.config import ROOT, AgentSettings
from src.tidebound.context.budget import FORMAT_MARGIN
from src.tidebound.context.compaction import assemble_context, input_budget, needs_compaction
from src.tidebound.errors import AgentError
from src.tidebound.prompting import load_character_bundle
from src.tidebound.runtime.compaction import CompactionCoordinator
from src.tidebound.runtime.preview import preview_sink, publish_preview
from src.tidebound.runtime.session import ChatSession
from src.tidebound.runtime.types import Message, ModelReply, RunRecord, ToolCall
from src.tidebound.storage.model_requests import ModelRequestStore
from src.tidebound.storage.runs import RunStore
from src.tidebound.storage.summaries import SummaryStore
from src.tidebound.tools.registry import create_tools, tool_definitions
from src.tidebound.workflows.compaction import N01, N02, N03, N04, N05, run_compaction
from src.tidebound.workflows.compaction.types import CompactionInput


def make_settings(root: Path) -> AgentSettings:
    """创建简短角色、世界观与真实压缩提示词组成的隔离测试配置。

    Args:
        root: 测试运行数据根目录。

    Returns:
        使用真实摘要指令但不依赖实际网络的配置。
    """
    prompts = root / "prompts"
    shutil.copytree(ROOT / "prompts" / "master", prompts / "master")
    shutil.copyfile(ROOT / "prompts" / "master.yaml", prompts / "master.yaml")
    (prompts / "master/chat.character/chat.character-zh.md").write_text("ROLE_SENTINEL", encoding="utf-8")
    (prompts / "master/world.worldview/world.worldview-zh.md").write_text("WORLD_SENTINEL", encoding="utf-8")
    return AgentSettings(base_url="http://fixture", model="fixture", data_dir=root / "data",
                         prompts_dir=prompts, context_limit=16384, max_output_tokens=1024)


def seed(store: RunStore, owner: str, count: int = 20, start: int = 0) -> list[RunRecord]:
    """写入含独立轮次标识的历史，供覆盖范围和重启测试使用。

    Args:
        store: 隔离的 Run 存储。
        owner: 测试账号。
        count: 新增历史轮数。
        start: 对话序号起点。

    Returns:
        已提交的按时间排序历史。
    """
    records = []
    for number in range(start, start + count):
        record = RunRecord(run_id=str(uuid4()), created_at=f"2026-01-01T00:{number:02d}:00Z",
            status="completed", user_content=f"事实{number}", messages=[
                Message(role="user", content=f"事实{number}" + "x" * 850),
                Message(role="assistant", content="已记录", reasoning_content="REASONING_SENTINEL")])
        store.save(owner, record)
        records.append(record)
    return records


class SummaryModel:
    def __init__(self, content: str = "用户不喝咖啡；尚未决定周末出行时间。") -> None:
        self.content = content
        self.inputs: list[dict[str, object]] = []

    async def complete(self, system: str, messages: list[Message], tools: list[dict[str, object]]) -> ModelReply:
        """捕获摘要输入，同时模拟不应泄漏到聊天窗口的流式内容。

        Args:
            system: 摘要系统指令。
            messages: 压缩来源资料。
            tools: 应为空的工具声明。

        Returns:
            可控的完整摘要。
        """
        assert "ROLE_SENTINEL" not in system
        assert not tools
        assert "REASONING_SENTINEL" not in messages[0].content
        self.inputs.append(json.loads(messages[0].content))
        publish_preview("SUMMARY_MUST_NOT_LEAK")
        return ModelReply(message=Message(role="assistant", content=self.content), finish_reason="stop")


class WaitingSummary(SummaryModel):
    def __init__(self) -> None:
        super().__init__()
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def complete(self, system: str, messages: list[Message], tools: list[dict[str, object]]) -> ModelReply:
        """模拟会在取消后仍返回的慢摘要供应商。

        Args:
            system: 摘要指令。
            messages: 摘要来源。
            tools: 空工具声明。

        Returns:
            延迟的摘要结果。
        """
        self.entered.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            await asyncio.sleep(0)
        return await super().complete(system, messages, tools)


def test_threshold_counts_reservations() -> None:
    settings = AgentSettings(context_limit=10000, max_output_tokens=1024)
    boundary = 9000 - settings.max_output_tokens - FORMAT_MARGIN
    assert not needs_compaction(boundary - 1, settings)
    assert needs_compaction(boundary, settings)
    assert needs_compaction(boundary + 20000, settings)


def test_small_budget_preserves_five_turns_instead_of_overcompressing(tmp_path: Path) -> None:
    """预算不足也不能把最后五轮纳入摘要。

    Args:
        tmp_path: 隔离合成历史目录。
    """
    async def scenario() -> None:
        settings = make_settings(tmp_path).model_copy(update={"context_limit": 20000, "max_output_tokens": 8192})
        runs, owner = RunStore(settings.data_dir), uuid4().hex
        records = seed(runs, owner, count=7)
        model = SummaryModel()
        with pytest.raises(AgentError, match="最近五轮"):
            await run_compaction(CompactionInput(owner, "", load_character_bundle(ROOT / "prompts").content,
                records, [], tool_definitions(create_tools("Asia/Shanghai")), settings),
                runs, SummaryStore(settings.data_dir), model)
        assert not model.inputs
        assert len(runs.list_runs(owner)) == 7
    asyncio.run(scenario())


def test_nodes_roll_forward_without_duplicate_coverage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证节点顺序、分批合并、连续压缩、重启和有效前缀恢复。

    Args:
        tmp_path: 隔离测试文件。
        monkeypatch: 记录真实节点调用顺序。
    """
    order: list[str] = []
    for module, name, label in [(N01, "read_source", "N01"), (N02, "build_plan", "N02"),
                                 (N04, "validate_summary", "N04"), (N05, "commit_summary", "N05")]:
        original = getattr(module, name)
        def wrapped(*args: object, _original: Callable[..., object] = original, _label: str = label) -> object:
            order.append(_label)
            return _original(*args)
        monkeypatch.setattr(module, name, wrapped)
    original_generate = N03.summarize_history
    async def wrapped_generate(*args: object) -> str:
        order.append("N03")
        return await original_generate(*args)
    monkeypatch.setattr(N03, "summarize_history", wrapped_generate)

    async def scenario() -> None:
        settings = make_settings(tmp_path)
        runs, summaries, owner = RunStore(settings.data_dir), SummaryStore(settings.data_dir), uuid4().hex
        records = seed(runs, owner)
        model = SummaryModel()
        previews: list[str] = []
        token = preview_sink.set(previews.append)
        try:
            first = await run_compaction(CompactionInput(owner, "", "ROLE_SENTINEL", records,
                [Message(role="user", content="CURRENT_SENTINEL")], [], settings), runs, summaries, model)
        finally:
            preview_sink.reset(token)
        assert order == ["N01", "N02", "N03", "N04", "N05"]
        assert first is not None and not previews
        assert first.covered_run_ids == [r.run_id for r in records[:-5]]
        assert first.input_after + 1024 + FORMAT_MARGIN <= settings.context_limit * 0.70
        assert len(first.content.encode()) <= int(input_budget(settings) * 0.15)
        assert len(model.inputs) >= 2  # 待摘要历史本身超过单次请求，按完整轮次分批。
        assert all("CURRENT_SENTINEL" not in json.dumps(item) for item in model.inputs)
        assert model.inputs[1]["previous_summary"] == model.content
        covered_ids = [turn["run_id"] for request in model.inputs for turn in request["turns"]]
        assert covered_ids == first.covered_run_ids
        assert len(runs.list_runs(owner)) == 20
        restored = SummaryStore(settings.data_dir).load(owner, "", [item.run_id for item in records])
        assert restored == first
        assert summaries.load(uuid4().hex, "", [item.run_id for item in records]) is None
        assert summaries.load(owner, "", first.covered_run_ids[:-1]) is None
        records += seed(runs, owner, count=18, start=20)
        second_model = SummaryModel("更新摘要：用户不喝咖啡；周末时间已改为周日。")
        second = await run_compaction(CompactionInput(owner, "", "ROLE_SENTINEL", records, [], [], settings),
                                     runs, summaries, second_model)
        assert second is not None and second.parent_id == first.summary_id
        assert second.covered_run_ids == [r.run_id for r in records[:-5]]
        assert second_model.inputs[0]["previous_summary"] == first.content
        newly_covered = [turn["run_id"] for request in second_model.inputs for turn in request["turns"]]
        assert newly_covered == second.covered_run_ids[len(first.covered_run_ids):]
        assert set(newly_covered).isdisjoint(first.covered_run_ids)
        assembled = assemble_context("ROLE_SENTINEL", records, [Message(role="user", content="now")],
                                     [], second, "summary rules")
        assert assembled.messages[0].role == "user"
        assert json.loads(assembled.messages[0].content)["context_summary"] == second.content
        assert assembled.messages[-1].content == "now"
    asyncio.run(scenario())


@pytest.mark.parametrize("content", ["", "太长" * 10000])
def test_bad_summary_never_reaches_commit(tmp_path: Path, content: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """无效输出只重试有限次数，不跳转提交节点。

    Args:
        tmp_path: 隔离存储。
        content: 无效模型输出。
        monkeypatch: 替换提交节点检测错误跳转。
    """
    def forbidden(*args: object) -> None:
        raise AssertionError("invalid output reached N05")
    monkeypatch.setattr(N05, "commit_summary", forbidden)
    async def scenario() -> None:
        settings = make_settings(tmp_path)
        runs, owner = RunStore(settings.data_dir), uuid4().hex
        records = seed(runs, owner)
        model = SummaryModel(content)
        with pytest.raises(AgentError, match="摘要"):
            await run_compaction(CompactionInput(owner, "", "role", records, [], [], settings),
                                 runs, SummaryStore(settings.data_dir), model)
        assert len(model.inputs) == 2
        assert not list(settings.data_dir.glob("*/summaries/**/*.json"))
    asyncio.run(scenario())


def test_background_finishes_after_main_reply_and_reset_discards_late_result(tmp_path: Path) -> None:
    """回复先完成，后台摘要不泄漏预览；重置后迟到结果不能发布。

    Args:
        tmp_path: 隔离存储与提示词。
    """
    async def scenario() -> None:
        settings = make_settings(tmp_path)
        # 保持本测试处于软阈值区间，容纳常驻安全规则及消息时间元数据。
        settings = settings.model_copy(update={"context_limit": 24576})
        waiting = WaitingSummary()
        class MainModel:
            async def complete(self, system: str, messages: list[Message], tools: list[dict[str, object]]) -> ModelReply:
                return ModelReply(message=Message(role="assistant", content="答复" * 300), finish_reason="stop")
        service = ChatSession(settings, MainModel(), summary_model=waiting)
        owner = uuid4().hex
        seed(service.store, owner, count=13)
        record = service.start(owner, str(uuid4()), "新问题")
        await service.active[owner].task
        assert record.status == "completed"
        await asyncio.wait_for(waiting.entered.wait(), 2)
        assert owner not in service.active
        assert not service.compaction.jobs[owner].task.done()
        assert record.preview == ""
        await service.reset_context(owner)
        assert service.compaction.summaries.load(owner, "", [item.run_id for item in service.store.list_runs(owner)]) is None
        assert service.records(owner) == []
        await service.close()
    asyncio.run(scenario())


def test_stop_waiting_main_run_does_not_cancel_committed_history_summary(tmp_path: Path) -> None:
    """硬超限请求可停止，历史后台任务独立完成且不含停止的当前输入。

    Args:
        tmp_path: 隔离运行数据。
    """
    async def scenario() -> None:
        settings = make_settings(tmp_path)
        runs, owner = RunStore(settings.data_dir), uuid4().hex
        records = seed(runs, owner)
        model = WaitingSummary()
        coordinator = CompactionCoordinator(runs, model)
        stop = asyncio.Event()
        pending = asyncio.create_task(coordinator.prepare(owner, "", "role", records,
            [Message(role="user", content="STOPPED_INPUT")], [], settings, str(uuid4()), stop))
        await model.entered.wait()
        stop.set()
        with pytest.raises(AgentError) as failure:
            await pending
        assert failure.value.code == "run_stopped"
        assert not coordinator.jobs[owner].task.done()
        model.release.set()
        summary = await coordinator.jobs[owner].task
        assert summary is not None
        assert "STOPPED_INPUT" not in json.dumps(model.inputs)
        await coordinator.close()
    asyncio.run(scenario())


def test_waited_summary_preserves_current_tool_chain(tmp_path: Path) -> None:
    """压缩历史后当前用户输入及调用—结果链保持完整。

    Args:
        tmp_path: 隔离存储。
    """
    async def scenario() -> None:
        settings = make_settings(tmp_path)
        runs, owner = RunStore(settings.data_dir), uuid4().hex
        records = seed(runs, owner)
        current = [Message(role="user", content="当前问题"), Message(role="assistant", tool_calls=[
            ToolCall(id="keep-call", name="get_current_time", arguments="{}")]),
            Message(role="tool", content="time result", tool_call_id="keep-call")]
        coordinator = CompactionCoordinator(runs, SummaryModel())
        prepared = await coordinator.prepare(owner, "", "role", records, current, [], settings,
                                             str(uuid4()), asyncio.Event())
        assert prepared.messages[-3:] == current
        assert prepared.input_used <= input_budget(settings)
        await coordinator.close()
    asyncio.run(scenario())


def test_soft_threshold_starts_one_background_job_without_waiting(tmp_path: Path) -> None:
    """90% 到硬上限之间仍正常发主请求，同账号只创建一个后台任务。

    Args:
        tmp_path: 隔离存储。
    """
    async def scenario() -> None:
        settings = make_settings(tmp_path)
        runs, owner = RunStore(settings.data_dir), uuid4().hex
        records = seed(runs, owner, count=13)
        base = assemble_context("role", records, [Message(role="user", content="")], [], None, "")
        size = input_budget(settings) - base.input_used - 20
        current = [Message(role="user", content="x" * size)]
        model = WaitingSummary()
        coordinator = CompactionCoordinator(runs, model)
        waiting_states: list[str] = []
        prepared = await asyncio.wait_for(coordinator.prepare(owner, "", "role", records, current, [], settings,
            str(uuid4()), asyncio.Event(), on_wait=lambda: waiting_states.append("compacting")), 1)
        assert waiting_states == []
        assert prepared.input_used <= input_budget(settings)
        task = coordinator.jobs[owner].task
        await model.entered.wait()
        second = await coordinator.prepare(owner, "", "role", records, current, [], settings,
                                           str(uuid4()), asyncio.Event())
        assert coordinator.jobs[owner].task is task and second.messages == prepared.messages
        model.release.set()
        assert await task is not None
        await coordinator.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("outcome", ["continue", "stop", "failure"])
def test_over_budget_run_exposes_workflow_wait_and_resumes_original_message(
    tmp_path: Path, outcome: str,
) -> None:
    """硬超限时展示整理阶段，继续、停止及失败都会退出等待状态。

    Args:
        tmp_path: 隔离存储与提示词。
        outcome: 模拟摘要成功、用户停止或摘要无效。
    """
    from webapp.chat_service import run_view, session_view

    async def scenario() -> None:
        settings = make_settings(tmp_path)
        summary_model = WaitingSummary()
        if outcome == "failure":
            summary_model.content = ""
        requests: list[list[Message]] = []

        class MainModel:
            async def complete(self, system: str, messages: list[Message],
                               tools: list[dict[str, object]]) -> ModelReply:
                """确认整理后恢复原请求及回复阶段。

                Args:
                    system: 已组装主提示词。
                    messages: 摘要、保留历史和原用户输入。
                    tools: 主模型工具声明。

                Returns:
                    固定的完整回复。
                """
                assert record.phase == "generating"
                requests.append(messages)
                return ModelReply(message=Message(role="assistant", content="继续回复原消息"), finish_reason="stop")

        settings = settings.model_copy(update={"context_limit": 24576})
        service = ChatSession(settings, MainModel(), summary_model=summary_model)
        owner = uuid4().hex
        seed(service.store, owner)
        record = service.start(owner, str(uuid4()), "保留这条原消息")
        task = service.active[owner].task
        await asyncio.wait_for(summary_model.entered.wait(), 2)
        assert record.status == "running" and record.phase == "compacting"
        assert not requests and not record.preview
        assert run_view(service.get(owner, record.run_id)).phase == "compacting"
        assert session_view(service, owner).active_run.phase == "compacting"
        assert "phase" not in record.model_dump()
        if outcome == "stop":
            service.stop(owner, record.run_id)
            await asyncio.wait_for(task, 2)
        summary_model.release.set()
        await asyncio.wait_for(task, 2)
        assert record.phase == "generating"
        if outcome == "continue":
            assert record.status == "completed" and len(requests) == 1
            assert requests[0][-1].content == "保留这条原消息"
            assert [message.content for message in record.messages] == ["保留这条原消息", "继续回复原消息"]
        else:
            assert record.status == ("stopped" if outcome == "stop" else "failed")
            assert not requests
        assert session_view(service, owner).active_run is None
        await service.close()
    asyncio.run(scenario())


def test_session_restart_uses_summary_but_keeps_display_history(tmp_path: Path) -> None:
    """真实会话入口恢复摘要，聊天展示仍保留原文且不展示摘要消息。

    Args:
        tmp_path: 隔离存储。
    """
    from webapp.chat_service import session_view

    async def scenario() -> None:
        settings = make_settings(tmp_path)
        runs, owner = RunStore(settings.data_dir), uuid4().hex
        records = seed(runs, owner)
        summary = await run_compaction(CompactionInput(owner, "", "ROLE_SENTINEL", records, [], [], settings),
                                      runs, SummaryStore(settings.data_dir), SummaryModel())
        assert summary is not None
        class MainModel:
            async def complete(self, system: str, messages: list[Message],
                               tools: list[dict[str, object]]) -> ModelReply:
                """检查摘要只进入模型上下文，不进入持久对话原文。

                Args:
                    system: 角色与摘要使用规则。
                    messages: 摘要、近期原文和当前用户输入。
                    tools: 主模型工具声明。

                Returns:
                    固定测试回复。
                """
                assert "历史摘要使用规则" in system
                assert json.loads(messages[0].content)["context_summary"] == summary.content
                assert messages[-1].content == "继续聊"
                return ModelReply(message=Message(role="assistant", content="好的"), finish_reason="stop")
        settings = settings.model_copy(update={"context_limit": 24576})
        restarted = ChatSession(settings, MainModel(), summary_model=SummaryModel())
        idle_usage = session_view(restarted, owner).context_usage
        assert idle_usage.input_used is not None
        assert idle_usage.input_used + settings.max_output_tokens + FORMAT_MARGIN < settings.context_limit * 0.70
        result = restarted.start(owner, str(uuid4()), "继续聊")
        await restarted.active[owner].task
        assert result.status == "completed"
        assert len(session_view(restarted, owner).messages) == 42
        assert all("context_summary" not in message.content for message in result.messages)
        await restarted.close()
    asyncio.run(scenario())


def test_background_model_requests_are_audited_without_tools_or_preview(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """通过真实 HTTP 适配器验证后台 purpose、独立调用次数和无工具请求。

    Args:
        tmp_path: 隔离模型请求快照。
        monkeypatch: 使用受控 HTTP 响应代替模型网络。
    """
    bodies: list[dict[str, object]] = []
    actual = httpx.AsyncClient

    def respond(request: httpx.Request) -> httpx.Response:
        """捕获摘要请求，返回完成摘要。

        Args:
            request: 实际 HTTP 请求。

        Returns:
            兼容 Chat Completions 的固定摘要。
        """
        body = json.loads(request.content)
        bodies.append(body)
        assert "tools" not in body and "tool_choice" not in body
        assert body["stream"] is False
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
            "role": "assistant", "content": "用户不喝咖啡，周末安排尚未确定。"}}]})

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: actual(transport=httpx.MockTransport(respond), **kw))

    async def scenario() -> None:
        settings = make_settings(tmp_path)
        runs, owner, run_id = RunStore(settings.data_dir), uuid4().hex, str(uuid4())
        records = seed(runs, owner)
        coordinator = CompactionCoordinator(runs)
        previews: list[str] = []
        token = preview_sink.set(previews.append)
        try:
            task = coordinator.schedule(owner, "", "ROLE_SENTINEL", records, [], [], settings, run_id)
            assert task is not None and await task is not None
        finally:
            preview_sink.reset(token)
        snapshots = ModelRequestStore(settings.data_dir).list_requests()
        assert len(snapshots) == len(bodies) >= 2
        assert all(item.purpose == "context.compaction" and item.run_id == run_id for item in snapshots)
        assert sorted(item.step for item in snapshots) == list(range(1, len(snapshots) + 1))
        assert not previews
        await coordinator.close()
    asyncio.run(scenario())


def test_manual_compaction_below_threshold_reuses_task(tmp_path: Path) -> None:
    """主动入口跳过阈值，重复点击复用任务，并保留原始历史。

    Args:
        tmp_path: 合成会话的隔离目录。
    """
    async def exercise() -> None:
        owner = str(uuid4())
        settings = make_settings(tmp_path)
        model = WaitingSummary()
        settings = settings.model_copy(update={"context_limit": 24576})
        session = ChatSession(settings, summary_model=model)
        records = seed(session.store, owner, count=10)
        system, material, tools = session.companion_budget_material(records, settings)
        prepared, _ = session.compaction.read_context(owner, "", system, records, material, tools, settings)
        assert not needs_compaction(prepared.input_used, settings)
        first = asyncio.create_task(session.compact_context(owner))
        await model.entered.wait()
        second = asyncio.create_task(session.compact_context(owner))
        await asyncio.sleep(0)
        model.release.set()
        results = await asyncio.gather(first, second)
        assert results[0] == results[1]
        assert results[0].input_used < prepared.input_used
        assert len(model.inputs) == 1
        assert len(session.records(owner)) == 10
        assert session.compacted_usage(owner) == results[0]
        assert not session.records(str(uuid4()))
        await session.close()

    asyncio.run(exercise())


def test_manual_compaction_reset_rejects_late_result(tmp_path: Path) -> None:
    """清空可取消手动整理，迟到响应不能发布或显示为成功。

    Args:
        tmp_path: 合成会话的隔离目录。
    """
    async def exercise() -> None:
        owner = str(uuid4())
        model = WaitingSummary()
        session = ChatSession(make_settings(tmp_path).model_copy(update={"context_limit": 24576}), summary_model=model)
        seed(session.store, owner, count=10)
        task = asyncio.create_task(session.compact_context(owner))
        await model.entered.wait()
        await session.reset_context(owner)
        with pytest.raises(AgentError, match="取消|变化"):
            await task
        assert session.compacted_usage(owner) is None
        assert session.records(owner) == []
        await session.close()

    asyncio.run(exercise())


def test_manual_compaction_failure_preserves_history(tmp_path: Path) -> None:
    """失败与空历史返回明确错误，不发布不合格摘要。

    Args:
        tmp_path: 合成会话的隔离目录。
    """
    async def exercise() -> None:
        owner = str(uuid4())
        model = SummaryModel(content="x" * 10000)
        session = ChatSession(make_settings(tmp_path).model_copy(update={"context_limit": 24576}), summary_model=model)
        with pytest.raises(AgentError, match="暂无新增"):
            await session.compact_context(owner)
        seed(session.store, owner, count=10)
        with pytest.raises(AgentError, match="整理未成功"):
            await session.compact_context(owner)
        assert len(session.records(owner)) == 10
        assert session.compacted_usage(owner) is None
        await session.close()

    asyncio.run(exercise())


def test_five_recent_turns_are_required_even_for_manual_compaction(tmp_path: Path) -> None:
    """不足六轮时无更早历史可压缩，手动入口也不得牺牲最近原文。

    Args:
        tmp_path: 合成历史的隔离目录。
    """
    async def scenario() -> None:
        settings = make_settings(tmp_path)
        runs, owner = RunStore(settings.data_dir), uuid4().hex
        records = seed(runs, owner, count=5)
        model = SummaryModel()
        with pytest.raises(AgentError, match="最近五轮"):
            await run_compaction(CompactionInput(owner, "", "ROLE_SENTINEL", records, [], [], settings,
                trigger="manual"), runs, SummaryStore(settings.data_dir), model)
        assert not model.inputs
    asyncio.run(scenario())
