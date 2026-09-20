"""用单次无历史、无工具的 instruct 调用润色即将展示的角色正文。"""

import asyncio
from dataclasses import dataclass

from src.tidebound.config import AgentSettings
from src.tidebound.context.budget import select_messages
from src.tidebound.errors import AgentError
from src.tidebound.llm import ModelClient
from src.tidebound.runtime.preview import preview_sink
from src.tidebound.runtime.types import Message, ModelReply
from src.tidebound.storage.model_requests import request_injection, request_purpose

ENHANCEMENT_PURPOSE = "emotion.enhancement"
VISIBLE_WORKFLOWS = frozenset({"chat.meet", "tools.websearch.reaction", "tools.websearch.delivery"})


@dataclass(frozen=True)
class EmotionEnhancementRun:
    """Run 开始时固定的独立模型、角色提示词与调用预算。"""

    settings: AgentSettings
    system: str
    model: ModelClient
    instruction: str

    def wrap(self, model: ModelClient) -> ModelClient:
        """包装本轮一个模型出口，内部工作流仍保持原有职责。

        Args:
            model: 原本负责推理、工具选择或表达的模型边界。

        Returns:
            只在用户可见正文出口增加润色的模型边界。
        """
        return EmotionEnhancedModel(model, self)

    async def polish(self, draft: str) -> str:
        """仅发送角色 system 和一条原稿，不重试或回退未润色正文。

        Args:
            draft: 已正常完成、即将对用户说出的单段回复原稿。

        Returns:
            通过完整性检查的润色正文。

        Raises:
            AgentError: 请求失败、超时、超出预算或润色结果不完整。
            OSError: 审计快照无法保存。
        """
        content = self.instruction + "\n\n" + draft
        messages = select_messages(self.system, [], [Message(role="user", content=content)], [], self.settings)
        purpose_token = request_purpose.set(ENHANCEMENT_PURPOSE)
        injection_token = request_injection.set(None)
        preview_token = preview_sink.set(None)
        try:
            try:
                async with asyncio.timeout(self.settings.timeout_seconds):
                    reply = await self.model.complete(self.system, messages, [])
            except TimeoutError as error:
                raise AgentError("emotion_timeout", "云端情感增强超时，本轮未提交。", 504) from error
            except AgentError as error:
                raise AgentError("emotion_model_error", f"云端情感增强失败：{error}", error.status) from error
            if (reply.finish_reason != "stop" or reply.message.role != "assistant"
                    or reply.message.tool_calls or not reply.message.content.strip()):
                raise AgentError("emotion_incomplete", "云端情感增强没有返回完整正文，本轮未提交。", 502)
            return reply.message.content.strip()
        finally:
            preview_sink.reset(preview_token)
            request_injection.reset(injection_token)
            request_purpose.reset(purpose_token)


class EmotionEnhancedModel:
    """阻止原稿预览，仅将真正对用户说话的模型结果交给润色模型。"""

    def __init__(self, upstream: ModelClient, enhancement: EmotionEnhancementRun) -> None:
        self.upstream = upstream
        self.enhancement = enhancement

    async def complete(self, system: str, messages: list[Message], tools: list[dict[str, object]]) -> ModelReply:
        """在可见回复出口隐藏原稿并替换正文，保持工具链与内部结果不变。

        Args:
            system: 原模型本次实际的系统提示词，不会发送给润色模型。
            messages: 原模型的有效上下文，不会整体转发给润色模型。
            tools: 原模型的工具声明，仍仅供原模型调用。

        Returns:
            原始工具或内部工作流结果，或保留消息元数据并替换正文的回复。

        Raises:
            AgentError: 原模型或润色模型失败。
            OSError: 请求审计无法保存。
        """
        purpose = request_purpose.get()
        visible = purpose in VISIBLE_WORKFLOWS or (purpose == "chat" and preview_sink.get() is not None)
        if not visible:
            return await self.upstream.complete(system, messages, tools)
        # 搜索内部草稿已有无预览上下文；工具前过渡文本也不应未经润色显示。
        preview_token = preview_sink.set(None)
        try:
            reply = await self.upstream.complete(system, messages, tools)
            if (reply.finish_reason != "stop" or reply.message.role != "assistant"
                    or reply.message.tool_calls or not reply.message.content.strip()):
                return reply
            content = await self.enhancement.polish(reply.message.content)
            return reply.model_copy(update={"message": reply.message.model_copy(update={"content": content})})
        finally:
            preview_sink.reset(preview_token)
