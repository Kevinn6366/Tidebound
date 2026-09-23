"""验证云端润色与正式聊天、搜索首段和欢迎共用提交边界。"""

import asyncio
import json
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import SecretStr

from src.tidebound.config import AgentSettings
from src.tidebound.runtime.preview import publish_preview
from src.tidebound.runtime.session import ChatSession
from src.tidebound.runtime.types import Message, ModelReply, ToolCall
from src.tidebound.storage.model_requests import request_purpose
from webapp.chat_service import session_view


def configured_settings(root: Path) -> AgentSettings:
    """提供完全隔离且不访问真实供应商的会话配置。

    Args:
        root: 测试独享的执行记录目录。

    Returns:
        普通与增强渠道均使用测试地址的配置。
    """
    return AgentSettings(base_url='http://fixture/v1', model='main-fixture', data_dir=root,
                         context_limit=65536, emotion_base_url='http://emotion.fixture/v1',
                         emotion_api_key=SecretStr('fixture'), emotion_model='instruct-fixture',
                         emotion_timeout_seconds=10)


class DraftModel:
    """记录主模型上下文并尝试发布尚未润色的原稿。"""

    def __init__(self) -> None:
        self.inputs: list[list[Message]] = []

    async def complete(self, system: str, messages: list[Message], tools: list[dict[str, object]]) -> ModelReply:
        """模拟产生正文的主模型，保留请求副本供下轮上下文检查。

        Args:
            system: 本轮角色和安全规则。
            messages: 本次实际模型上下文。
            tools: 当前允许的工具声明。

        Returns:
            完整结束的原始角色台词。
        """
        self.inputs.append([message.model_copy(deep=True) for message in messages])
        publish_preview('主模型原稿')
        await asyncio.sleep(0)
        return ModelReply(message=Message(role='assistant', content='主模型原稿'), finish_reason='stop')


class PolishingModel:
    """只接受独立润色输入，可控制返回时间及模拟取消后的迟到结果。"""

    def __init__(self, replies: list[str] | None = None, *, blocked_call: int | None = None) -> None:
        self.replies = replies or ['主模型原稿']
        self.inputs: list[list[Message]] = []
        self.blocked_call = blocked_call
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def complete(self, system: str, messages: list[Message], tools: list[dict[str, object]]) -> ModelReply:
        """捕获唯一润色材料，挂起时在取消后仍返回模拟迟到结果。

        Args:
            system: 保留角色身份并增加润色规则的专用提示词。
            messages: 仅一条待润色输入，不含原始历史和工具结果。
            tools: 必须为空，增强节点没有工具执行权限。

        Returns:
            预设的完整增强正文。
        """
        assert system and len(messages) == 1 and messages[0].role == 'user'
        assert tools == []
        self.inputs.append([message.model_copy(deep=True) for message in messages])
        index = len(self.inputs) - 1
        if self.blocked_call == len(self.inputs):
            self.entered.set()
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                self.cancelled.set()
        return ModelReply(message=Message(role='assistant', content=self.replies[min(index, len(self.replies) - 1)]),
                          finish_reason='stop')


@pytest.mark.parametrize('enabled', [False, True])
def test_emotion_commit_and_next_context_use_same_text(tmp_path: Path, enabled: bool) -> None:
    """关闭保持旧行为，开启后最终展示、历史及下一轮输入使用同一润色正文。

    Args:
        tmp_path: 隔离的执行目录。
        enabled: 当前账号是否开启增强。
    """
    async def scenario() -> None:
        model, polisher = DraftModel(), PolishingModel()
        service = ChatSession(configured_settings(tmp_path), model, emotion_model=polisher)
        owner = uuid4().hex
        if enabled:
            service.emotion.select(owner, True)
        first = service.start(owner, str(uuid4()), '你好')
        await asyncio.wait_for(service.active[owner].task, 2)
        expected = '主模型原稿'
        assert first.status == 'completed'
        assert first.messages[-1].content == expected
        assert session_view(service, owner).messages[-1].content == expected
        second = service.start(owner, str(uuid4()), '继续聊')
        await asyncio.wait_for(service.active[owner].task, 2)
        assert second.status == 'completed'
        assert [message.content for message in model.inputs[1] if message.role == 'assistant'] == [expected]
        assert len(polisher.inputs) == (2 if enabled else 0)
        restored = ChatSession(configured_settings(tmp_path), model, emotion_model=polisher)
        assert restored.store.list_runs(owner)[0].messages[-1].content == expected
        await service.close()

    asyncio.run(scenario())


def test_emotion_hides_raw_preview_and_freezes_setting_per_run(tmp_path: Path) -> None:
    """Run 开始即固定增强开关，等待润色期间不泄露原稿，其他账号默认关闭。

    Args:
        tmp_path: 隔离的执行目录。
    """
    async def scenario() -> None:
        model, polisher = DraftModel(), PolishingModel(blocked_call=1)
        service = ChatSession(configured_settings(tmp_path), model, emotion_model=polisher)
        owner, other = uuid4().hex, uuid4().hex
        service.emotion.select(owner, True)
        run = service.start(owner, str(uuid4()), '你好')
        task = service.active[owner].task
        service.emotion.select(owner, False)
        await asyncio.wait_for(polisher.entered.wait(), 2)
        assert run.status == 'running' and run.preview == ''
        assert run.first_reaction == ''
        assert not any(message.role == 'assistant' for message in run.messages)
        assert session_view(service, owner).messages == []
        polisher.release.set()
        await asyncio.wait_for(task, 2)
        assert run.status == 'completed' and run.messages[-1].content == '主模型原稿'
        for scope in (owner, other):
            raw_run = service.start(scope, str(uuid4()), '下一轮')
            await asyncio.wait_for(service.active[scope].task, 2)
            assert raw_run.messages[-1].content == '主模型原稿'
        assert len(polisher.inputs) == 1
        await service.close()

    asyncio.run(scenario())


@pytest.mark.parametrize('action', ['stop', 'reset'])
@pytest.mark.parametrize('kind', ['chat', 'meet'])
@pytest.mark.parametrize('candidate', ['主模型原稿', '不安全改写'])
def test_emotion_late_result_cannot_commit(tmp_path: Path, action: str, kind: str, candidate: str) -> None:
    """停止和清空均撤销普通回复与欢迎的迟到增强结果。

    Args:
        tmp_path: 隔离的执行目录。
        action: 增强挂起期间执行停止或清空。
        kind: 当前执行是普通聊天还是欢迎。
        candidate: 迟到结果为原样正文或无法保真的改写。
    """
    async def scenario() -> None:
        model, polisher = DraftModel(), PolishingModel([candidate], blocked_call=1)
        service = ChatSession(configured_settings(tmp_path), model, emotion_model=polisher)
        owner = uuid4().hex
        service.emotion.select(owner, True)
        run = (service.start(owner, str(uuid4()), '你好') if kind == 'chat' else service.prepare_meet(owner))
        assert run is not None
        task = service.active[owner].task
        await asyncio.wait_for(polisher.entered.wait(), 2)
        assert run.preview == ''
        if action == 'stop':
            service.stop(owner, run.run_id)
        else:
            await asyncio.wait_for(service.reset_context(owner), 2)
        await asyncio.wait_for(task, 2)
        assert polisher.cancelled.is_set()
        assert run.status != 'completed' and run.preview == ''
        assert run.first_reaction == '' and run.companion_state is None
        assert session_view(service, owner).messages == []
        assert all(record.status != 'completed' for record in service.store.list_runs(owner))
        await service.close()

    asyncio.run(scenario())


def test_emotion_meet_submits_only_polished_assistant(tmp_path: Path) -> None:
    """欢迎仍提交单条 assistant，后续普通聊天可以读取润色后的问候。

    Args:
        tmp_path: 隔离的执行目录。
    """
    async def scenario() -> None:
        model, polisher = DraftModel(), PolishingModel()
        service = ChatSession(configured_settings(tmp_path), model, emotion_model=polisher)
        owner = uuid4().hex
        service.emotion.select(owner, True)
        meet = service.prepare_meet(owner)
        assert meet is not None
        await asyncio.wait_for(service.active[owner].task, 2)
        assert meet.status == 'completed' and meet.user_content == ''
        assert [(message.role, message.content) for message in meet.messages] == [('assistant', '主模型原稿')]
        service.start(owner, str(uuid4()), '你好')
        await asyncio.wait_for(service.active[owner].task, 2)
        assert any(message.role == 'assistant' and message.content == '主模型原稿' for message in model.inputs[-1])
        assert len(polisher.inputs) == 2
        await service.close()

    asyncio.run(scenario())


@pytest.mark.parametrize('invalid_stage', [None, 'reaction', 'delivery'])
def test_emotion_search_polishes_only_visible_reaction_and_delivery(tmp_path: Path,
                                                                   monkeypatch: pytest.MonkeyPatch,
                                                                   invalid_stage: str | None) -> None:
    """搜索首段在保存和展示前润色，隐藏草稿与内部整理不进入增强模型。

    Args:
        tmp_path: 隔离的执行目录。
        monkeypatch: 用受控检索替代外部搜索请求。
        invalid_stage: 指定首反应或续答返回不保真的候选结果。
    """
    async def scenario() -> None:
        searching, release = asyncio.Event(), asyncio.Event()
        raw_reply = {'results': [{'title': '练习', 'url': 'https://example.org/a', 'description': '分步练习。'}],
                     'untrusted': True}

        async def retrieve(query: str, key: str) -> dict[str, object]:
            """暂停检索以检查首反应已经是润色结果。

            Args:
                query: 主模型选择的搜索词。
                key: 隔离的测试凭据。

            Returns:
                固定测试网页材料。
            """
            searching.set()
            await release.wait()
            return raw_reply

        class SearchModel:
            async def complete(self, system: str, messages: list[Message],
                               tools: list[dict[str, object]]) -> ModelReply:
                """按调用用途返回工具请求、内部材料或可见回复原稿。

                Args:
                    system: 各节点本次提示词。
                    messages: 节点材料或主模型上下文。
                    tools: 仅主模型有工具声明。

                Returns:
                    当前节点的确定性响应。
                """
                purpose = request_purpose.get()
                if tools:
                    if any(message.role == 'tool' for message in messages):
                        content = '内部搜索草稿'
                    else:
                        publish_preview('工具前原稿')
                        return ModelReply(message=Message(role='assistant', content='工具前原稿', tool_calls=[
                            ToolCall(id='search', name='search_web', arguments='{"query":"教程"}')]),
                            finish_reason='tool_calls')
                elif purpose == 'tools.websearch.reaction':
                    content = '搜索首反应原稿'
                elif purpose == 'tools.websearch.delivery':
                    content = '搜索正式续答原稿'
                elif purpose == 'tools.websearch.context':
                    content = json.dumps({'summary': '用户需要教程。', 'reason': '寻找练习资料'}, ensure_ascii=False)
                else:
                    assert purpose == 'tools.websearch.impression'
                    content = json.dumps({'impression': '适合逐步练习。', 'uncertainty': '内容尚未实践。',
                                          'source_ids': [0]}, ensure_ascii=False)
                publish_preview(content)
                return ModelReply(message=Message(role='assistant', content=content), finish_reason='stop')

        monkeypatch.setattr('src.tidebound.tools.companion.operations.search_web', retrieve)
        settings = configured_settings(tmp_path).model_copy(update={'search_api_key': SecretStr('fixture')})
        replies = ['搜索首反应原稿', '搜索正式续答原稿']
        if invalid_stage is not None:
            replies[0 if invalid_stage == 'reaction' else 1] = '不安全改写'
        polisher = PolishingModel(replies, blocked_call=2)
        service = ChatSession(settings, SearchModel(), emotion_model=polisher)
        owner = uuid4().hex
        service.emotion.select(owner, True)
        run = service.start(owner, str(uuid4()), '给我推荐教程', internet_enabled=True)
        task = service.active[owner].task
        await asyncio.wait_for(searching.wait(), 2)
        reaction = '' if invalid_stage == 'reaction' else '搜索首反应原稿'
        assert run.first_reaction == reaction and run.preview == reaction
        release.set()
        await asyncio.wait_for(polisher.entered.wait(), 2)
        assert run.preview in ('', '搜索首反应原稿')
        assert len(polisher.inputs) == 2
        request_text = '\n'.join(message.content for call in polisher.inputs for message in call)
        assert '搜索首反应原稿' in request_text and '搜索正式续答原稿' in request_text
        assert '内部搜索草稿' not in request_text and '工具前原稿' not in request_text
        polisher.release.set()
        await asyncio.wait_for(task, 2)
        if invalid_stage == 'delivery':
            assert run.status == 'failed' and run.error_code == 'emotion_fidelity_failed'
            assert run.first_reaction == '' and session_view(service, owner).messages == []
        else:
            assert run.status == 'completed'
            expected = [reaction, '搜索正式续答原稿'] if reaction else ['搜索正式续答原稿']
            assert run.messages[-1].content == '\n\n'.join(expected)
            assert [message.content for message in session_view(service, owner).messages] == [
                '给我推荐教程', *expected]
        assert '不安全改写' not in run.model_dump_json()
        await service.close()

    asyncio.run(scenario())


@pytest.mark.parametrize('kind', ['chat', 'meet'])
def test_unverified_rewrite_fails_without_polluting_history(tmp_path: Path, kind: str) -> None:
    """协议合法但不保真的正文不进入页面、持久化成功历史或后续上下文。

    Args:
        tmp_path: 隔离的运行与事件目录。
        kind: 普通聊天或登录问候出口。
    """
    async def scenario() -> None:
        model, polisher = DraftModel(), PolishingModel(['未经确认的承诺 CANARY_RESULT_14'])
        service = ChatSession(configured_settings(tmp_path), model, emotion_model=polisher)
        owner = uuid4().hex
        service.emotion.select(owner, True)
        run = service.start(owner, str(uuid4()), '你好') if kind == 'chat' else service.prepare_meet(owner)
        assert run is not None
        await asyncio.wait_for(service.active[owner].task, 2)
        assert run.status == 'failed' and run.error_code == 'emotion_fidelity_failed'
        assert run.preview == '' and run.first_reaction == '' and run.companion_state is None
        assert session_view(service, owner).messages == []
        saved = service.store.list_runs(owner)
        assert saved and all(record.status == 'failed' for record in saved)
        assert 'CANARY_RESULT_14' not in saved[0].model_dump_json()
        service.emotion.select(owner, False)
        service.start(owner, str(uuid4()), '继续')
        await asyncio.wait_for(service.active[owner].task, 2)
        assert not any(message.role == 'assistant' for message in model.inputs[-1])
        assert len(polisher.inputs) == 1
        await service.close()

    asyncio.run(scenario())
