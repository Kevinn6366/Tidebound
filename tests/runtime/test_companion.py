"""陪伴能力的提交、撤销、来源、隔离和联网授权回归。"""
import asyncio
import json
from pathlib import Path
from uuid import uuid4

from src.tidebound.config import AgentSettings
from src.tidebound.runtime.session import ChatSession
from src.tidebound.runtime.types import Message, ModelReply, RunRecord, ToolCall
from src.tidebound.storage.companion import CompanionState
from src.tidebound.tools.companion.arguments import ReadPastArguments
from src.tidebound.tools.companion.operations import CompanionTools
from src.tidebound.tools.registry import create_tools, invoke_tool_async, register_companion_tools


def reply(content: str = '已记下') -> ModelReply:
    return ModelReply(message=Message(role='assistant', content=content), finish_reason='stop')


class CompanionModel:
    """识别结构化测试操作，摘要分支独立于主模型工具链。"""

    def __init__(self) -> None:
        self.operation = 'remember_fact'
        self.source = ''
        self.target = ''
        self.summary_calls = 0
        self.tool_names: list[str] = []
        self.inputs: list[list[Message]] = []
        self.last_result: dict[str, object] = {}
        self.fail_final = False
        self.block_summary = False
        self.entered = asyncio.Event()

    async def complete(self, system: str, messages: list[Message], tools: list[dict[str, object]]) -> ModelReply:
        """模拟主工具选择、摘要生成和最终回复。

        Args:
            system: 已注入规则的系统正文。
            messages: 当前可见资料。
            tools: 当前权限允许的声明；摘要请求为空。

        Returns:
            可控模型响应。
        """
        if not tools:
            self.summary_calls += 1
            self.entered.set()
            if self.block_summary:
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    pass  # 特意模拟取消后仍返回的供应商。
            return reply(json.dumps({'summary': '面试事项', 'condition': '下次相关交流时'}))
        self.tool_names = [line.split('(', 1)[0] for line in tools[0]['function']['description'].splitlines()[1:]]
        self.inputs.append(messages)
        if messages[-1].role == 'tool':
            self.last_result = json.loads(messages[-1].content)
            return ModelReply(message=Message(role='assistant', content='已处理'),
                              finish_reason='length' if self.fail_final else 'stop')
        if self.operation == 'none':
            return reply()
        content = messages[-1].content
        if self.operation == 'read_past_conversation':
            args = {'query': ''}
        elif self.operation == 'list_followups':
            args = {'status': 'all'}
        elif self.operation == 'search_web':
            args = {'query': '新闻'}
        else:
            args = {'source_run_id': self.source, 'evidence': content}
            if self.operation == 'remember_fact':
                args['fact'] = content
            elif self.operation in ('create_followup', 'update_followup', 'save_interest'):
                args['topic'] = content
            if self.operation in ('update_followup', 'cancel_followup'):
                args['followup_id'] = self.target
            if self.operation == 'update_followup':
                args['status'] = 'completed'
        return ModelReply(message=Message(role='assistant', tool_calls=[ToolCall(
            id='call', name=self.operation, arguments=json.dumps(args))]), finish_reason='tool_calls')


async def run(service: ChatSession, owner: str, model: CompanionModel, text: str, *, online: bool = False) -> RunRecord:
    """执行一轮并等待提交以检查真实存储边界。

    Args:
        service: 隔离会话服务。
        owner: 测试账号。
        model: 主模型替身。
        text: 用户正文。
        online: 本轮是否授权联网。

    Returns:
        执行终态。
    """
    model.source = str(uuid4())
    record = service.start(owner, model.source, text, internet_enabled=online)
    await asyncio.wait_for(service.active[owner].task, 2)
    return record


def test_state_commit_followup_workflow_restart_and_reset(tmp_path: Path) -> None:
    """验证事实、跟进创建更新取消、重启、用户隔离及主动删除。"""
    async def scenario() -> None:
        settings = AgentSettings(base_url='http://fixture', model='test', data_dir=tmp_path, context_limit=65536)
        model = CompanionModel()
        service = ChatSession(settings, model)
        owner, other = uuid4().hex, uuid4().hex
        fact = await run(service, owner, model, '我不喝咖啡')
        assert fact.status == 'completed' and len(fact.companion_state.facts) == 1
        other_record = await run(service, other, model, '我喜欢茶')
        model.operation = 'create_followup'
        followup = await run(service, owner, model, '明天我要面试')
        assert followup.status == 'completed' and model.summary_calls == 1
        model.target = followup.companion_state.followups[0].id
        model.operation = 'update_followup'
        updated = await run(service, owner, model, '面试已结束')
        assert updated.companion_state.followups[0].status == 'completed'
        model.operation = 'cancel_followup'
        cancelled = await run(service, owner, model, '不要再提面试了')
        assert cancelled.companion_state.followups[0].status == 'cancelled'
        assert model.summary_calls == 3
        model.operation = 'list_followups'
        restarted = ChatSession(settings, model)
        await run(restarted, owner, model, '查看事项')
        assert model.last_result['followups'][0]['status'] == 'cancelled'
        assert any('我不喝咖啡' in m.content for m in model.inputs[-1])
        await run(restarted, other, model, '查看事项')
        assert model.last_result['followups'] == []
        await restarted.reset_context(owner)
        assert all(not r.messages and not r.user_content and r.companion_state is None
                   for r in restarted.store.list_runs(owner))
        assert restarted.get(other, other_record.run_id).user_content == '我喜欢茶'
        model.operation = 'read_past_conversation'
        await run(restarted, owner, model, '还记得吗')
        assert model.last_result['turns'] == []
        await service.close()
        await restarted.close()
    asyncio.run(scenario())


def test_failed_and_stopped_writes_do_not_commit(tmp_path: Path) -> None:
    """最终回复失败及摘要迟到均不能保存暂存状态。"""
    async def scenario() -> None:
        model = CompanionModel()
        service = ChatSession(AgentSettings(base_url='http://fixture', model='test', data_dir=tmp_path), model)
        owner = uuid4().hex
        model.fail_final = True
        record = await run(service, owner, model, '不要保存这条失败事实')
        assert record.status == 'failed' and record.companion_state is None
        model.fail_final = False
        model.operation = 'create_followup'
        model.block_summary = True
        model.source = str(uuid4())
        record = service.start(owner, model.source, '明天面试')
        task = service.active[owner].task
        await asyncio.wait_for(model.entered.wait(), 2)
        service.stop(owner, record.run_id)
        await asyncio.wait_for(task, 2)
        assert record.status == 'stopped' and record.companion_state is None
        model.operation = 'list_followups'
        await run(service, owner, model, '查看')
        assert model.last_result['followups'] == []
        await service.close()
    asyncio.run(scenario())


def test_network_gate_and_source_validation(tmp_path: Path) -> None:
    """关闭联网时没有声明且伪造调用被拒绝，错误来源不能写入事实。"""
    async def scenario() -> None:
        model = CompanionModel()
        service = ChatSession(AgentSettings(base_url='http://fixture', model='test', data_dir=tmp_path), model)
        owner = uuid4().hex
        model.operation = 'search_web'
        await run(service, owner, model, '查询', online=False)
        assert 'search_web' not in model.tool_names
        assert model.last_result['error'] == 'unknown_tool'
        await run(service, owner, model, '查询', online=True)
        assert {'search_web', 'read_webpage', 'get_weather', 'save_interest', 'check_interest_updates'} <= set(model.tool_names)
        assert model.last_result['error'] == 'search_not_configured'
        current = service.records(owner)[-1]
        state = CompanionState()
        companion = CompanionTools([], current, state, model, service.settings, asyncio.Event())
        registry = create_tools('UTC')
        register_companion_tools(registry, companion, internet_enabled=False)
        for source, evidence in [(str(uuid4()), '查询'), (current.run_id, '这是模型编造的事实')]:
            result = await invoke_tool_async(registry, ToolCall(id='x', name='remember_fact', arguments=json.dumps({
                'fact': '伪造', 'source_run_id': source, 'evidence': evidence})))
            assert json.loads(result.content)['error'] == 'invalid_evidence'
            assert '逐字复制' in json.loads(result.content)['message']
        assert not state.facts
        await service.close()
    asyncio.run(scenario())


def test_history_read_ignores_tool_and_reasoning_content(tmp_path: Path) -> None:
    """历史回看不暴露工具回填、思考和未提交执行。"""
    record = RunRecord(run_id=str(uuid4()), created_at='', status='completed', user_content='用户原话', messages=[
        Message(role='user', content='用户原话'), Message(role='tool', content='秘密工具资料', tool_call_id='x'),
        Message(role='assistant', content='最终答复', reasoning_content='秘密推理')])
    service = CompanionTools([record], record, CompanionState(), CompanionModel(), AgentSettings(), asyncio.Event())
    result = service.read_past(ReadPastArguments())
    assert '用户原话' in json.dumps(result, ensure_ascii=False)
    assert '秘密' not in json.dumps(result, ensure_ascii=False)
    assert service.read_past(ReadPastArguments(query='秘密'))['turns'] == []
    record.user_content = '前' * 1200 + '后续原文'
    first = service.read_past(ReadPastArguments(run_id=record.run_id))['turns'][0]
    assert first['next_content_offset'] == 1200
    second = service.read_past(ReadPastArguments(run_id=record.run_id, content_offset=1200))['turns'][0]
    assert second['user'] == '后续原文' and second['next_content_offset'] is None


def test_invalid_followup_summary_does_not_stage_a_change(tmp_path: Path) -> None:
    """摘要结构校验失败后不创建事项，也不把模型正文作为成功结果。"""
    class InvalidSummary:
        async def complete(self, system: str, messages: list[Message], tools: list[dict[str, object]]) -> ModelReply:
            return reply('这不是所要求的 JSON')
    async def scenario() -> None:
        record = RunRecord(run_id=str(uuid4()), created_at='', user_content='明天面试')
        state = CompanionState()
        service = CompanionTools([], record, state, InvalidSummary(), AgentSettings(data_dir=tmp_path), asyncio.Event())
        tools = create_tools('UTC')
        register_companion_tools(tools, service, internet_enabled=False)
        result = await invoke_tool_async(tools, ToolCall(id='x', name='create_followup', arguments=json.dumps({
            'source_run_id': record.run_id, 'evidence': record.user_content, 'topic': '面试'})))
        assert json.loads(result.content)['error'] == 'tool_execution_failed'
        assert state.followups == []
    asyncio.run(scenario())


def test_current_evidence_alias_saves_actual_run_id(tmp_path: Path) -> None:
    """当前来源由后端解析，保存真实 ID，仍拒绝不匹配的原文。

    Args:
        tmp_path: 隔离测试配置目录。
    """
    async def scenario() -> None:
        record = RunRecord(run_id=str(uuid4()), created_at='', user_content='我喜欢薄荷茶')
        state = CompanionState()
        service = CompanionTools([], record, state, CompanionModel(), AgentSettings(data_dir=tmp_path), asyncio.Event())
        tools = create_tools('UTC')
        register_companion_tools(tools, service, internet_enabled=False)
        result = await invoke_tool_async(tools, ToolCall(id='x', name='remember_fact', arguments=json.dumps({
            'fact': '喜欢薄荷茶', 'evidence': '我喜欢薄荷茶'})))
        assert json.loads(result.content)['fact']['source_run_id'] == record.run_id
        assert state.facts[0].source_run_id == record.run_id
    asyncio.run(scenario())
