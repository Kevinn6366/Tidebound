"""验证预算调整不会改变进行中的工具调用循环。"""
import asyncio
from pathlib import Path
from uuid import uuid4

from src.tidebound.config import AgentSettings
from src.tidebound.runtime.session import ChatSession
from src.tidebound.runtime.types import Message, ModelReply
from tests.runtime.test_agent import ScriptedModel, final_reply, tool_reply


def test_budget_snapshot_is_fixed_until_next_run(tmp_path: Path) -> None:
    """执行中保存新预算，当前工具后请求保持原值，下一轮采用新值。

    Args:
        tmp_path: 隔离的执行记录目录。
    """
    async def scenario() -> None:
        """在首次模型调用中修改预算以模拟管理员并发操作。"""
        owner = str(uuid4())
        service = ChatSession(AgentSettings(data_dir=tmp_path, base_url='http://localhost', model='test'))

        class UpdatingModel(ScriptedModel):
            async def complete(self, system: str, messages: list[Message],
                               tools: list[dict[str, object]]) -> ModelReply:
                """在请求已选取材料后保存下一轮预算。

                Args:
                    system: 本轮系统提示词。
                    messages: 已选取的请求消息。
                    tools: 当前工具定义。

                Returns:
                    预设工具调用或最终回复。
                """
                service.update_context_budget(owner, 65536)
                return await super().complete(system, messages, tools)

        model = UpdatingModel([tool_reply(), final_reply()])
        service.model = model
        first = service.start(owner, str(uuid4()), '时间')
        await service.active[owner].task
        assert first.status == 'completed'
        assert len(model.inputs) == 2
        assert first.context_usage.total == service.settings.context_limit
        second = service.start(owner, str(uuid4()), '继续')
        await service.active[owner].task
        assert second.status == 'completed'
        assert second.context_usage.total == 65536
        await service.close()

    asyncio.run(scenario())
