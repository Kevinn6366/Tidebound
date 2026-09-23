"""长期摘要的并发追赶、来源、清空、预算和工具接入回归。"""

import asyncio
import json
from pathlib import Path
from uuid import uuid4

import pytest

from src.tidebound.config import AgentSettings
from src.tidebound.errors import AgentError
from src.tidebound.memory.rolling_summary import ConversationMemory
from src.tidebound.runtime.preview import preview_sink
from src.tidebound.runtime.rolling_summary import RollingSummaryCoordinator
from src.tidebound.runtime.session import ChatSession
from src.tidebound.runtime.types import Message, ModelReply, RunRecord, ToolCall
from src.tidebound.storage.companion import CompanionState
from src.tidebound.storage.model_requests import request_purpose, request_run
from src.tidebound.storage.rolling_summaries import RollingSummaryStore
from src.tidebound.storage.runs import RunStore
from src.tidebound.tools.companion.operations import CompanionTools
from src.tidebound.tools.registry import create_tools, invoke_tool_async, register_companion_tools
from src.tidebound.workflows.rolling_summary import generate_summary


def record(index: int, text: str = '准备面试', *, status: str = 'completed') -> RunRecord:
    """构造具有明确历史顺序的轮次。

    Args:
        index: 秒级顺序编号。
        text: 用户正文。
        status: 所需执行终态。

    Returns:
        可持久化的隔离测试记录。
    """
    return RunRecord(run_id=uuid4().hex, created_at=f'2026-09-22T10:00:{index:02d}+00:00',
                     user_content=text, status=status,
                     messages=[Message(role='user', content=text),
                               Message(role='assistant', content='我们一起准备', reasoning_content='不可读取的思考')])


class MemoryModel:
    def __init__(self) -> None:
        self.inputs: list[dict[str, object]] = []
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.block = False
        self.invalid = False
        self.late = False

    async def complete(self, system: str, messages: list[Message], tools: list[dict[str, object]]) -> ModelReply:
        """生成引用真实输入的摘要，可模拟阻塞及取消后迟到。

        Args:
            system: 独立长期记忆提示词。
            messages: 旧摘要和新增历史。
            tools: 必须为空的工具集合。

        Returns:
            有来源的摘要或可控非法来源。
        """
        assert '长期对话记忆' in system and not tools
        assert preview_sink.get() is None
        assert request_purpose.get() == 'memory.rolling_summary'
        payload = json.loads(messages[0].content)
        if 'review_candidate' in payload:
            return ModelReply(message=Message(role='assistant', content=json.dumps(payload['review_candidate'], ensure_ascii=False)),
                              finish_reason='stop')
        assert 'reasoning_content' not in messages[0].content
        assert '不可读取的思考' not in messages[0].content
        self.inputs.append(payload)
        self.entered.set()
        if self.block:
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                if not self.late:
                    raise
        entries = payload['previous_summary']['entries'] + [{
            'category': 'topic', 'content': turn['user'][:80],
            'evidence_refs': ['foreign'] if self.invalid else [next(key for key, source in payload['sources'].items()
                if source['run_ids'] == [turn['run_id']] and source['speaker'] == 'user')],
            'attribution': 'user_statement', 'event_time': None,
        } for turn in payload['turns']]
        return ModelReply(message=Message(role='assistant', content=json.dumps({'entries': entries}, ensure_ascii=False)),
                          finish_reason='stop')


def settings(root: Path, **updates: object) -> AgentSettings:
    """建立无需网络的独立后台预算配置。

    Args:
        root: 测试数据目录。
        updates: 本场景需要覆盖的合法配置字段。

    Returns:
        立即调度后台工作的测试配置。
    """
    return AgentSettings(base_url='http://fixture', model='test', data_dir=root,
                         rolling_summary_delay_seconds=0, **updates)


def test_background_catches_up_and_reader_isolates_history(tmp_path: Path) -> None:
    """生成期间继续提交，旧执行只读其历史范围，重启仍能恢复。"""
    async def scenario() -> None:
        runs = RunStore(tmp_path)
        owner, other = uuid4().hex, uuid4().hex
        first, second = record(1), record(2, '已经通过初试')
        runs.save(owner, first)
        model = MemoryModel()
        model.block = True
        coordinator = RollingSummaryCoordinator(runs, settings(tmp_path), model)
        task = coordinator.schedule(owner, '')
        await model.entered.wait()
        runs.save(owner, second)
        assert coordinator.schedule(owner, '') is task
        before = ConversationMemory(runs, owner, '', [first, second]).read()
        assert before['status'] == 'not_generated' and before['uncovered_turn_count'] == 2
        model.release.set()
        await task
        assert len(model.inputs) == 2
        assert len(model.inputs[1]['turns']) == 1
        assert model.inputs[1]['source_turns'][0]['run_id'] == first.run_id
        assert model.inputs[1]['source_turns'][0]['user'] == first.user_content
        assert model.inputs[1]['source_turns'][0]['assistant'] == '我们一起准备'
        latest = ConversationMemory(runs, owner, '', [first, second]).read()
        assert latest['covered_through_run_id'] == second.run_id
        assert latest['uncovered_turn_count'] == 0
        assert latest['generated_at'] != latest['covered_through_at']
        older = ConversationMemory(runs, owner, '', [first]).read()
        assert older['covered_through_run_id'] == first.run_id
        assert '初试' not in json.dumps(older, ensure_ascii=False)
        assert ConversationMemory(runs, other, '', [first]).read()['status'] == 'not_generated'
        await coordinator.close()
        restarted = RollingSummaryCoordinator(runs, settings(tmp_path), model)
        await restarted.schedule(owner, '')
        assert len(model.inputs) == 2
        await restarted.close()
    asyncio.run(scenario())


def test_invalid_candidate_keeps_previous_and_cancelled_late_result_cannot_publish(tmp_path: Path) -> None:
    """非法来源不覆盖旧版，清空后的迟到结果也不能恢复旧记忆。"""
    async def scenario() -> None:
        runs = RunStore(tmp_path)
        owner = uuid4().hex
        first, second = record(1), record(2)
        runs.save(owner, first)
        model = MemoryModel()
        coordinator = RollingSummaryCoordinator(runs, settings(tmp_path), model)
        await coordinator.schedule(owner, '')
        original = coordinator.summaries.load(owner, '', [first.run_id])
        runs.save(owner, second)
        model.invalid = True
        await coordinator.schedule(owner, '')
        assert coordinator.summaries.load(owner, '', [first.run_id, second.run_id]) == original
        model.invalid = False
        model.block = model.late = True
        model.entered.clear()
        coordinator.schedule(owner, '')
        await model.entered.wait()
        runs.reset_context(owner)
        await coordinator.cancel(owner)
        runs.delete_conversation_history(owner)
        assert not list(coordinator.summaries.directory(owner, '').glob('*.json'))
        assert ConversationMemory(runs, owner, '', [first]).read()['status'] == 'invalidated'
        await coordinator.close()
    asyncio.run(scenario())


def test_batches_preserve_sources_and_budget_failure_is_explicit(tmp_path: Path) -> None:
    """长历史按完整轮次分批，单轮过大时不默默丢弃原文。"""
    async def scenario() -> None:
        model = MemoryModel()
        from src.tidebound.prompting import load_prompt_bundles
        prompt = load_prompt_bundles(settings(tmp_path).prompts_dir, ('memory.rolling_summary',)).content
        config = settings(tmp_path).model_copy(update={'context_limit': len(prompt.encode()) + 6500, 'max_output_tokens': 512})
        records = [record(i, '面试练习' * 100) for i in range(1, 5)]
        summary = await generate_summary(None, records, config, model)
        assert len(model.inputs) > 1
        assert {source for entry in summary.content.entries for source in entry.source_run_ids} == {r.run_id for r in records}
        with pytest.raises(AgentError, match='预算不足'):
            await generate_summary(None, [record(5, '超长' * 10000)], config, model)
    asyncio.run(scenario())


def test_followup_receives_memory_and_uncovered_turns_without_generation(tmp_path: Path) -> None:
    """独立读取工具和跟进共用摘要，证据校验仍拒绝模型伪造。"""
    async def scenario() -> None:
        runs = RunStore(tmp_path)
        owner = uuid4().hex
        first, second, current = record(1), record(2, '通过初试'), record(3, '不去复试了', status='running')
        config = settings(tmp_path)
        memory_model = MemoryModel()
        summary = await generate_summary(None, [first], config, memory_model)
        RollingSummaryStore(tmp_path).save(owner, summary)
        reader = ConversationMemory(runs, owner, '', [first, second])
        payloads: list[dict[str, object]] = []

        class FollowupModel:
            async def complete(self, system: str, messages: list[Message], tools: list[dict[str, object]]) -> ModelReply:
                """捕获跟进节点输入并返回合法摘要。

                Args:
                    system: 跟进专用规则。
                    messages: 跟进资料及长期背景。
                    tools: 无工具权限声明。

                Returns:
                    合法跟进摘要。
                """
                payloads.append(json.loads(messages[0].content))
                return ModelReply(message=Message(role='assistant', content='{"summary":"不去复试","condition":"不再主动追问"}'), finish_reason='stop')

        service = CompanionTools([first, second], current, CompanionState(), FollowupModel(), config,
                                 asyncio.Event(), memory=reader)
        registry = create_tools(config.timezone)
        register_companion_tools(registry, service, internet_enabled=False)
        result = await invoke_tool_async(registry, ToolCall(id='read', name='read_conversation_summary', arguments='{}'))
        assert json.loads(result.content)['uncovered_turn_count'] == 1
        rejected = await invoke_tool_async(registry, ToolCall(id='read', name='read_conversation_summary', arguments='{"owner":"other"}'))
        assert json.loads(rejected.content)['error'] == 'invalid_arguments'
        created = await invoke_tool_async(registry, ToolCall(id='create', name='create_followup', arguments=json.dumps({
            'topic': '复试', 'evidence': current.user_content})))
        assert 'error' not in json.loads(created.content)
        background = payloads[0]['conversation_memory']
        assert background['summary']['entries'][0]['source_run_ids'] == [first.run_id]
        assert [turn['run_id'] for turn in background['uncovered_turns']] == [second.run_id]
        invalid = await invoke_tool_async(registry, ToolCall(id='invalid', name='create_followup', arguments='{"topic":"复试","evidence":"伪造"}'))
        assert json.loads(invalid.content)['error'] == 'invalid_evidence'
        assert len(payloads) == 1 and len(memory_model.inputs) == 1
    asyncio.run(scenario())


def test_session_commit_schedules_memory_and_reset_deletes_it(tmp_path: Path) -> None:
    """真实会话协调链中后台不阻塞主回复，失败轮次不进入记忆。"""
    async def scenario() -> None:
        class ChatModel:
            async def complete(self, system: str, messages: list[Message], tools: list[dict[str, object]]) -> ModelReply:
                """返回可提交的聊天正文。

                Args:
                    system: 角色规则。
                    messages: 主模型上下文。
                    tools: 本轮工具目录。

                Returns:
                    最终角色回复。
                """
                return ModelReply(message=Message(role='assistant', content='我们一起准备'), finish_reason='stop')

        memory_model = MemoryModel()
        memory_model.block = True
        service = ChatSession(settings(tmp_path, context_limit=65536), ChatModel(), rolling_summary_model=memory_model)
        owner = uuid4().hex
        current = service.start(owner, uuid4().hex, '准备面试')
        await service.active[owner].task
        assert current.status == 'completed' and owner not in service.active
        await memory_model.entered.wait()
        assert not service.rolling_summary.jobs[owner].done()
        memory_model.release.set()
        await service.rolling_summary.jobs[owner]
        summary = service.rolling_summary.summaries.load(owner, '', [current.run_id])
        assert summary is not None
        assert request_run.get() is None
        failed = record(59, '失败内容', status='failed')
        service.store.save(owner, failed)
        await service.rolling_summary.schedule(owner, '')
        assert len(memory_model.inputs) == 1
        await service.reset_context(owner)
        assert not list(service.rolling_summary.summaries.directory(owner, '').glob('*.json'))
        await service.close()
    asyncio.run(scenario())


def test_stopping_main_run_does_not_cancel_committed_memory(tmp_path: Path) -> None:
    """停止未提交回复时，旧历史维护继续且不纳入被停止输入。"""
    async def scenario() -> None:
        entered, release = asyncio.Event(), asyncio.Event()

        class WaitingChat:
            async def complete(self, system: str, messages: list[Message], tools: list[dict[str, object]]) -> ModelReply:
                """等待测试放行，模拟可被停止的主请求。

                Args:
                    system: 主模型规则。
                    messages: 主模型材料。
                    tools: 可用能力目录。

                Returns:
                    停止后不得提交的迟到回复。
                """
                entered.set()
                await release.wait()
                return ModelReply(message=Message(role='assistant', content='迟到的主回复'), finish_reason='stop')

        memory_model = MemoryModel()
        memory_model.block = True
        service = ChatSession(settings(tmp_path, context_limit=65536), WaitingChat(), rolling_summary_model=memory_model)
        owner = uuid4().hex
        old = record(1)
        service.store.save(owner, old)
        current = service.start(owner, uuid4().hex, '不能进入摘要的新输入')
        main_task = service.active[owner].task
        await entered.wait()
        await memory_model.entered.wait()
        service.stop(owner, current.run_id)
        release.set()
        await main_task
        assert current.status == 'stopped'
        assert not service.rolling_summary.jobs[owner].done()
        memory_model.release.set()
        await service.rolling_summary.jobs[owner]
        summary = service.rolling_summary.summaries.load(owner, '', [old.run_id])
        assert summary.covered_run_ids == [old.run_id]
        assert '不能进入摘要' not in summary.model_dump_json()
        await service.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('mode', ['length', 'oversize', 'json', 'write'])
def test_generation_and_publication_failures_preserve_last_version(tmp_path: Path, mode: str) -> None:
    """模型截断、非法输出和落盘失败均不能破坏上个可读版本。"""
    async def scenario() -> None:
        runs = RunStore(tmp_path)
        owner = uuid4().hex
        first, second = record(1), record(2)
        runs.save(owner, first)
        model = MemoryModel()
        coordinator = RollingSummaryCoordinator(runs, settings(tmp_path), model)
        await coordinator.schedule(owner, '')
        original = coordinator.summaries.load(owner, '', [first.run_id])
        runs.save(owner, second)

        class BrokenModel:
            async def complete(self, system: str, messages: list[Message], tools: list[dict[str, object]]) -> ModelReply:
                """返回指定失败种类的输出。

                Args:
                    system: 长期摘要规则。
                    messages: 摘要输入资料。
                    tools: 空工具列表。

                Returns:
                    可控失败输出。
                """
                response = await model.complete(system, messages, tools)
                if mode == 'length':
                    response.finish_reason = 'length'
                elif mode == 'oversize':
                    response.message.content = '字' * 12000
                elif mode == 'json':
                    response.message.content = '不是JSON'
                return response

        coordinator.model = BrokenModel()
        if mode == 'write':
            def fail_save(owner: str, summary: object) -> None:
                """模拟原子发布前磁盘故障。

                Args:
                    owner: 发布账号。
                    summary: 尚未写入的候选版本。

                Raises:
                    OSError: 模拟磁盘不可写。
                """
                raise OSError('test disk failure')
            coordinator.summaries.save = fail_save
        await coordinator.schedule(owner, '')
        assert coordinator.summaries.load(owner, '', [first.run_id, second.run_id]) == original
        await coordinator.close()
    asyncio.run(scenario())


def test_invalid_summary_retries_once_before_publication(tmp_path: Path) -> None:
    """真实供应商偶发非法结构时，第二次合法结果才能发布。"""
    async def scenario() -> None:
        class TransientModel(MemoryModel):
            async def complete(self, system: str, messages: list[Message], tools: list[dict[str, object]]) -> ModelReply:
                """首个响应损坏，第二个保留合法资料。

                Args:
                    system: 长期摘要规则。
                    messages: 同一份原始资料。
                    tools: 空工具集合。

                Returns:
                    首次非法、后续合法的JSON。
                """
                result = await super().complete(system, messages, tools)
                if len(self.inputs) == 1:
                    result.message.content += '}'
                return result
        runs = RunStore(tmp_path)
        owner = uuid4().hex
        turn = record(1)
        runs.save(owner, turn)
        model = TransientModel()
        coordinator = RollingSummaryCoordinator(runs, settings(tmp_path), model)
        await coordinator.schedule(owner, '')
        assert len(model.inputs) == 2
        assert model.inputs[0]['turns'] == model.inputs[1]['turns']
        assert not model.inputs[0]['validation_feedback']
        assert model.inputs[1]['validation_feedback']
        assert coordinator.summaries.load(owner, '', [turn.run_id]) is not None
        await coordinator.close()
    asyncio.run(scenario())


def test_source_replay_respects_budget_and_only_reads_referenced_history(tmp_path: Path) -> None:
    """回查仅使用旧条目引用的原文，预算不足时不影响新增轮次生成。"""
    from src.tidebound.context.budget import measure_input
    from src.tidebound.context.compaction import input_budget
    from src.tidebound.prompting import load_prompt_bundles
    from src.tidebound.storage.rolling_summaries import MemoryContent, MemoryEntry, RollingSummary

    async def scenario() -> None:
        old, unreferenced, new = record(1, '旧原文' * 4000), record(2, '不应回查'), record(3, '新进展')
        previous = RollingSummary(timeline_id='', covered_run_ids=[old.run_id, unreferenced.run_id],
                                  covered_through_at=unreferenced.created_at, prompt_hash='old', model='test',
                                  content=MemoryContent(entries=[MemoryEntry(category='topic', content='旧话题',
                                      source_run_ids=[old.run_id], attribution='inference')]))
        prompt = load_prompt_bundles(settings(tmp_path).prompts_dir, ('memory.rolling_summary',)).content
        config = settings(tmp_path).model_copy(update={'context_limit': len(prompt.encode()) + 5000,
                                                       'max_output_tokens': 512})
        model = MemoryModel()
        result = await generate_summary(previous, [old, unreferenced, new], config, model)
        payload = model.inputs[-1]
        assert payload['source_turns'] == []
        assert payload['turns'][0]['run_id'] == new.run_id
        assert result.covered_run_ids[-1] == new.run_id
        assert measure_input(prompt, [Message(role='user', content=json.dumps(payload, ensure_ascii=False))], []) <= input_budget(config)
        old.user_content = '旧原文'
        await generate_summary(previous, [old, unreferenced, new], config, model)
        assert [r['run_id'] for r in model.inputs[-1]['source_turns']] == [old.run_id]
    asyncio.run(scenario())


@pytest.mark.parametrize('case', ['wrong_speaker', 'invented_quote', 'missing_quote', 'wrong_source'])
def test_evidence_rejects_false_attribution(case: str) -> None:
    """错误说话者、伪造引句、无证据和错挂来源均不得成为确定事实。"""
    from src.tidebound.storage.rolling_summaries import MemoryContent, MemoryEntry, MemoryEvidence
    from src.tidebound.workflows.rolling_summary import validate_evidence

    original = record(1, '只是询问，没有确认')
    evidence = MemoryEvidence(run_id=original.run_id, speaker='user', quote='只是询问')
    entry = MemoryEntry(category='topic', content='用户仅询问', source_run_ids=[original.run_id],
                        attribution='user_statement', evidence=[evidence])
    if case == 'wrong_speaker':
        evidence.speaker = 'assistant'
        evidence.quote = '我们一起准备'
    elif case == 'invented_quote':
        evidence.quote = '用户确认了助手观点'
    elif case == 'missing_quote':
        entry.evidence = []
    else:
        evidence.run_id = uuid4().hex
    with pytest.raises(ValueError):
        validate_evidence(MemoryContent(entries=[entry]), MemoryContent(entries=[]), [original])


def test_verified_evidence_can_survive_without_replaying_old_turn() -> None:
    """已验证引句可跨版本沿用，但不得替换为新造的同来源引句。"""
    from src.tidebound.storage.rolling_summaries import MemoryContent, MemoryEntry, MemoryEvidence
    from src.tidebound.workflows.rolling_summary import validate_evidence

    original = record(1, '先用 Python，后来改 Markdown')
    content = MemoryContent(entries=[MemoryEntry(category='topic', content=original.user_content,
        source_run_ids=[original.run_id], attribution='user_statement',
        evidence=[MemoryEvidence(run_id=original.run_id, speaker='user', quote=original.user_content)])])
    validate_evidence(content, MemoryContent(entries=[]), [original])
    validate_evidence(content, content, [])
    changed = content.model_copy(deep=True)
    changed.entries[0].evidence[0].quote = '一直使用 Markdown'
    with pytest.raises(ValueError):
        validate_evidence(changed, content, [])


@pytest.mark.parametrize('invalid_review', [False, True])
def test_review_is_required_and_revalidated(tmp_path: Path, invalid_review: bool) -> None:
    """独立复核必须实际执行，复核后伪造引句仍不能发布。"""
    class ReviewingModel(MemoryModel):
        reviewed = False

        async def complete(self, system: str, messages: list[Message], tools: list[dict[str, object]]) -> ModelReply:
            """返回有明确复核痕迹的候选，或注入无依据引句。

            Args:
                system: 后台摘要规则。
                messages: 生成或复核输入。
                tools: 应为空的工具声明。

            Returns:
                用于检验发布边界的结构化候选。
            """
            payload = json.loads(messages[0].content)
            if 'review_candidate' in payload:
                self.reviewed = True
                candidate = payload['review_candidate']
                entry = candidate['entries'][0]
                entry['content'] = '复核后的用户表达'
                if invalid_review:
                    entry['evidence_refs'] = ['不存在的证据']
                return ModelReply(message=Message(role='assistant', content=json.dumps(candidate)), finish_reason='stop')
            return await super().complete(system, messages, tools)

    async def scenario() -> None:
        model = ReviewingModel()
        if invalid_review:
            with pytest.raises(ValueError):
                await generate_summary(None, [record(1)], settings(tmp_path), model)
        else:
            result = await generate_summary(None, [record(1)], settings(tmp_path), model)
            assert result.content.entries[0].content == '复核后的用户表达'
        assert model.reviewed
    asyncio.run(scenario())
