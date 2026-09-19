"""统一能力入口的压缩、参数校验、权限和注入边界。"""
import asyncio
import json

from src.tidebound.config import AgentSettings
from src.tidebound.prompting import load_tool_injections
from src.tidebound.runtime.agent_loop import agent_loop
from src.tidebound.runtime.types import Message, ModelReply, ToolCall
from src.tidebound.tools.companion.arguments import SearchArguments
from src.tidebound.tools.registry import create_tools, invoke_tool_async, tool_definitions


def test_dispatch_validates_envelope_permission_and_business_arguments() -> None:
    async def scenario() -> None:
        registry = create_tools('UTC')
        definitions = tool_definitions(registry)
        assert len(definitions) == 1
        assert definitions[0]['function']['name'] == 'use_tool'
        assert 'search_web' not in definitions[0]['function']['description']
        for name, arguments, expected in [
            ('get_current_time', {}, None),
            ('search_web', {'query': 'test'}, 'unknown_tool'),
            ('get_current_time', {'owner': 'another'}, 'invalid_arguments'),
        ]:
            call = ToolCall(id='wrapper', name='use_tool', arguments=json.dumps({'name': name, 'arguments': arguments}))
            result = await invoke_tool_async(registry, call)
            assert result.tool_call_id == 'wrapper'
            assert json.loads(result.content).get('error') == expected
        malformed = ToolCall(id='bad', name='use_tool', arguments='{"name":"get_current_time","arguments":[]}')
        assert json.loads((await invoke_tool_async(registry, malformed)).content)['error'] == 'invalid_arguments'
        registry['search_web'] = {'description': '搜索', 'arguments': SearchArguments, 'execute': lambda args: {'ok': True}}
        oversized = ToolCall(id='long', name='use_tool', arguments=json.dumps({'name': 'search_web', 'arguments': {'query': 'x' * 301}}))
        assert json.loads((await invoke_tool_async(registry, oversized)).content)['error'] == 'invalid_arguments'
    asyncio.run(scenario())


def test_dispatch_keeps_search_tail_rule_and_original_call_id() -> None:
    async def scenario() -> None:
        registry = create_tools('UTC')
        registry['search_web'] = {'description': '搜索', 'arguments': SearchArguments,
            'tail_injection': 'tools.injection.websearch', 'execute': lambda args: {'impression': '信息不确定'}}

        class Model:
            async def complete(self, system: str, messages: list[Message],
                               tools: list[dict[str, object]]) -> ModelReply:
                """检查统一入口触发的搜索表达注入。

                Args:
                    system: 当前完整系统提示词。
                    messages: 本轮工具链。
                    tools: 模型可见的统一入口。

                Returns:
                    预设搜索请求或最终回复。
                """
                if messages[-1].role == 'tool':
                    assert messages[-1].tool_call_id == 'wrapper'
                    tail = load_tool_injections(AgentSettings().prompts_dir, ('tools.injection.websearch',))
                    assert system.endswith(tail)
                    return ModelReply(message=Message(role='assistant', content='这点还不确定。'), finish_reason='stop')
                assert tools[0]['function']['name'] == 'use_tool'
                return ModelReply(message=Message(role='assistant', tool_calls=[ToolCall(id='wrapper', name='use_tool',
                    arguments='{"name":"search_web","arguments":{"query":"最新消息"}}')]), finish_reason='tool_calls')

        messages = await agent_loop('角色', [], [Message(role='user', content='聊聊近况')], Model(),
                                    AgentSettings(), asyncio.Event(), registry)
        assert messages[1].tool_calls[0].name == 'use_tool'
        assert messages[-1].content == '这点还不确定。'
    asyncio.run(scenario())


def test_json_string_arguments_and_safe_missing_field_feedback() -> None:
    """兼容 JSON 字符串参数，并指出缺失 query，不回显错误输入。"""
    async def scenario() -> None:
        registry = {'search_web': {'description': '搜索', 'arguments': SearchArguments,
                                  'execute': lambda args: {'ok': True}}}
        good = ToolCall(id='good', name='use_tool', arguments=json.dumps({
            'name': 'search_web', 'arguments': json.dumps({'query': 'Python'})}))
        assert json.loads((await invoke_tool_async(registry, good)).content) == {'ok': True}
        bad = ToolCall(id='bad', name='use_tool', arguments=json.dumps({
            'name': 'search_web', 'arguments': json.dumps({'PRIVATE_FIELD': 'SECRET'})}))
        result = await invoke_tool_async(registry, bad)
        parsed = json.loads(result.content)
        assert parsed['required'] == ['query']
        assert {'field': 'query', 'reason': 'missing'} in parsed['issues']
        assert 'SECRET' not in result.content and 'PRIVATE_FIELD' not in result.content
    asyncio.run(scenario())
