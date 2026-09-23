"""搜索整理节点遇到真实模型结构错误时的有限重试。"""
import asyncio
import json

import pytest
from pydantic import ValidationError

from src.tidebound.config import AgentSettings
from src.tidebound.runtime.types import Message, ModelReply
from src.tidebound.workflows.websearch.nodes import SearchContext, generate


@pytest.mark.parametrize('persistent', [False, True])
def test_overlong_reason_retries_with_schema(persistent: bool) -> None:
    """40字符限制不放宽，重试携带结构约束且最多两次。"""
    async def scenario() -> None:
        payloads: list[dict[str, object]] = []

        class Model:
            async def complete(self, system: str, messages: list[Message], tools: list[dict[str, object]]) -> ModelReply:
                """重现搜索目的超长并观察纠错输入。

                Args:
                    system: 搜索语境规则。
                    messages: 原始资料和可选的结构纠错信息。
                    tools: 空工具列表。

                Returns:
                    首次超长，重试按场景决定是否纠正。
                """
                payloads.append(json.loads(messages[0].content))
                reason = '过长的搜索目的' * 20 if persistent or len(payloads) == 1 else '了解版本更新'
                return ModelReply(message=Message(role='assistant', content=json.dumps({'summary': '用户关心版本变化', 'reason': reason})), finish_reason='stop')

        call = generate('tools.websearch.context', {'query': '版本更新'}, SearchContext, Model(), AgentSettings(), asyncio.Event())
        if persistent:
            with pytest.raises(ValidationError):
                await call
        else:
            assert (await call).reason == '了解版本更新'
        assert len(payloads) == 2
        assert payloads[1]['query'] == '版本更新'
        assert payloads[1]['required_output_schema']['properties']['reason']['maxLength'] == 40
    asyncio.run(scenario())
