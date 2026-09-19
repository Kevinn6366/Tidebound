"""独立续答节点不泄露草稿、保留证据边界并遵守停止。"""
import asyncio
import json

import pytest

from src.tidebound.config import AgentSettings
from src.tidebound.errors import AgentError
from src.tidebound.runtime.preview import preview_sink, publish_preview
from src.tidebound.runtime.types import Message, ModelReply
from src.tidebound.workflows.websearch.delivery import search_reply


@pytest.mark.parametrize('outcome', ['complete', 'stop', 'invalid', 'error'])
def test_delivery_hides_draft_and_checks_commit_boundary(outcome: str) -> None:
    """表达节点保留角色和有效语境，停止或非法输出不能形成最终回复。"""
    async def scenario() -> None:
        stop = asyncio.Event()
        previews: list[str] = []
        current = [Message(role='user', content='最近的新发现？'),
                   Message(role='tool', content='{"uncertainty":"日期不确定"}', tool_call_id='t')]
        if outcome == 'error':
            current[-1].content = '{"error":"tool_execution_failed","message":"工具故障"}'
        calls = 0

        class Model:
            async def complete(self, system: str, messages: list[Message],
                               tools: list[dict[str, object]]) -> ModelReply:
                """验证隐藏草稿与独立表达的模型边界。

                Args:
                    system: 当前阶段规则。
                    messages: 当前阶段输入。
                    tools: 主阶段允许的工具，交付阶段必须为空。

                Returns:
                    受控草稿或表达结果。
                """
                nonlocal calls
                calls += 1
                if calls == 1:
                    assert preview_sink.get() is None
                    publish_preview('我又搜了一遍。')
                    return ModelReply(message=Message(role='assistant', content='我又搜了一遍。'), finish_reason='stop')
                assert not tools
                assert system.startswith('角色快照\n世界观快照\n\n')
                payload = json.loads(messages[-1].content)
                assert payload['question'] == current[0].content
                assert 'draft' not in payload
                if outcome == 'error':
                    assert json.loads(payload['tool_results'][0]) == {
                        'status': 'not_completed', 'information_status': 'unknown'}
                    assert '工具故障' not in str(payload)
                else:
                    assert payload['tool_results'] == [current[1].content]
                assert payload['conversation'] == [
                    {'role': 'user', 'content': '历史摘要：先前讨论的股票'},
                    {'role': 'assistant', 'content': 'OLD_HISTORY'},
                    {'role': 'user', 'content': current[0].content},
                ]
                assert 'PRIVATE_REASONING' not in json.dumps(payload)
                publish_preview('日期还不能确定。')
                if outcome == 'stop':
                    stop.set()
                return ModelReply(message=Message(role='assistant', content='日期还不能确定。'),
                                  finish_reason='length' if outcome == 'invalid' else 'stop')

        token = preview_sink.set(previews.append)
        try:
            call = search_reply('角色快照\n世界观快照', [
                Message(role='user', content='历史摘要：先前讨论的股票'),
                Message(role='assistant', content='OLD_HISTORY', reasoning_content='PRIVATE_REASONING'),
                *current, Message(role='system', content='临时搜索规则')],
                                [{'type': 'function'}], current, Model(), AgentSettings(), stop)
            if outcome in ('complete', 'error'):
                reply = await call
                assert reply.message.content == '日期还不能确定。'
            else:
                with pytest.raises(AgentError):
                    await call
            assert previews == ['日期还不能确定。']
            assert preview_sink.get() == previews.append
            assert len(current) == 2
        finally:
            preview_sink.reset(token)
    asyncio.run(scenario())
