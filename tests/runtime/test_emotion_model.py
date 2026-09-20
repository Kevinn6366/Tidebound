"""验证云端润色的请求边界、独立配置、审计与失败策略。"""

import asyncio
import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from src.tidebound.config import AgentSettings
from src.tidebound.errors import AgentError
from src.tidebound.runtime.emotion_enhancement import EmotionEnhancement
from src.tidebound.runtime.preview import preview_sink, publish_preview
from src.tidebound.runtime.types import Message, ModelReply, ToolCall
from src.tidebound.storage.model_requests import ModelRequestStore, request_injection, request_purpose, request_run
from src.tidebound.workflows.emotion_enhancement import EmotionEnhancementRun


class DraftModel:
    """模拟原模型正文预览，并返回带内部思考的原始消息。"""

    async def complete(self, system: str, messages: list[Message], tools: list[dict[str, object]]) -> ModelReply:
        """提供固定原稿并尝试发布它，供调用边界验证。

        Args:
            system: 原模型规则。
            messages: 原模型上下文。
            tools: 原模型获准的工具。

        Returns:
            尚未润色、带有独立思考字段的角色原稿。
        """
        publish_preview("原稿：明天 8:30 见。")
        return ModelReply(message=Message(role="assistant", content="明天 8:30 见。",
                                         reasoning_content="internal-reasoning"), finish_reason="stop")


def test_instruct_request_contains_only_system_and_draft(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """独立请求不携带主模型资料，预览不泄漏原稿，审计仅保存无凭据正文。

    Args:
        tmp_path: 隔离设置与审计目录。
        monkeypatch: 替换 HTTP 传输，禁止连接真实云端。
    """
    async def scenario() -> None:
        settings = AgentSettings(data_dir=tmp_path, debug=True, reasoning_effort="max",
            api_key="main-secret", base_url="https://main.test/v1", model="main-model",
            emotion_base_url="https://emotion.test/v1", emotion_model="instruct", emotion_api_key="emotion-secret")
        captured: list[httpx.Request] = []

        def handle(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(200, json={"choices": [{"message": {
                "role": "assistant", "content": "明天 8:30 见呀。"}, "finish_reason": "stop"}]})

        actual_client = httpx.AsyncClient
        monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: actual_client(
            transport=httpx.MockTransport(handle), **kwargs))
        owner, run_id = uuid4().hex, str(uuid4())
        service = EmotionEnhancement(settings)
        service.select(owner, True)
        enhancement = service.prepare(owner)
        assert enhancement is not None
        previews: list[str] = []
        preview = preview_sink.set(previews.append)
        run = request_run.set((owner, run_id))
        injection = request_injection.set("main-private-injection")
        try:
            result = await enhancement.wrap(DraftModel()).complete("main-private-system", [
                Message(role="user", content="private-history"),
                Message(role="tool", content="private-tool-result", tool_call_id="old-tool"),
            ], [{"type": "function", "function": {"name": "private_tool"}}])
        finally:
            request_injection.reset(injection)
            request_run.reset(run)
            preview_sink.reset(preview)
        assert result.message.content == "明天 8:30 见呀。"
        assert result.message.reasoning_content == "internal-reasoning"
        assert not previews
        assert len(captured) == 1
        request = captured[0]
        assert str(request.url) == "https://emotion.test/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer emotion-secret"
        body = json.loads(request.content)
        assert body["model"] == "instruct" and body["stream"] is False
        assert "tools" not in body and "reasoning_effort" not in body
        assert body["messages"] == [
            {"role": "system", "content": enhancement.system},
            {"role": "user", "content": enhancement.instruction + "\n\n明天 8:30 见。"},
        ]
        assert "你是亚托莉" in enhancement.system and "水菜萌" in enhancement.system
        saved = ModelRequestStore(tmp_path).list_requests()
        assert len(saved) == 1 and saved[0].purpose == "emotion.enhancement"
        snapshot = ModelRequestStore(tmp_path).get(saved[0].request_id)
        assert snapshot.injection is None
        assert "secret" not in snapshot.model_dump_json()
        assert "private-" not in snapshot.model_dump_json()
        assert request_purpose.get() == "chat" and preview_sink.get() is None

    asyncio.run(scenario())


@pytest.mark.parametrize("purpose", ["context.compaction", "workflow.followup", "tools.websearch.context",
                                      "tools.websearch.impression", "chat"])
def test_internal_nodes_and_hidden_drafts_do_not_call_instruct(purpose: str) -> None:
    """内部节点与无预览的主模型搜索草稿不能触发额外润色。

    Args:
        purpose: 内部调用的审计分类，chat 场景模拟主动关闭预览的隐藏草稿。
    """
    class NoCallModel(DraftModel):
        async def complete(self, system: str, messages: list[Message], tools: list[dict[str, object]]) -> ModelReply:
            raise AssertionError("internal node must not call instruct")

    async def scenario() -> None:
        enhancement = EmotionEnhancementRun(AgentSettings(), "atri", NoCallModel(), "请润色原稿：")
        token = request_purpose.set(purpose)
        try:
            result = await enhancement.wrap(DraftModel()).complete("system", [], [])
        finally:
            request_purpose.reset(token)
        assert result.message.content == "明天 8:30 见。"

    asyncio.run(scenario())


@pytest.mark.parametrize("invalid", [
    ModelReply(message=Message(role="assistant", content="partial"), finish_reason="length"),
    ModelReply(message=Message(role="assistant", content="   "), finish_reason="stop"),
    ModelReply(message=Message(role="user", content="wrong role"), finish_reason="stop"),
    ModelReply(message=Message(role="assistant", content="tool", tool_calls=[
        ToolCall(id="call", name="get_current_time", arguments="{}")]), finish_reason="stop"),
])
def test_invalid_polish_fails_without_returning_draft(invalid: ModelReply) -> None:
    """润色结果协议错误时拒绝把原稿或不完整结果交付。

    Args:
        invalid: 供应商可能返回的非法润色响应。
    """
    class InvalidModel(DraftModel):
        async def complete(self, system: str, messages: list[Message], tools: list[dict[str, object]]) -> ModelReply:
            return invalid

    async def scenario() -> None:
        enhancement = EmotionEnhancementRun(AgentSettings(), "atri", InvalidModel(), "请润色原稿：")
        token = preview_sink.set(lambda _: None)
        try:
            with pytest.raises(AgentError, match="没有返回完整正文"):
                await enhancement.wrap(DraftModel()).complete("main", [], [])
        finally:
            preview_sink.reset(token)

    asyncio.run(scenario())


def test_polish_timeout_cancels_request_and_restores_context() -> None:
    """独立润色超时取消等待，不泄漏临时审计或预览上下文。"""
    async def scenario() -> None:
        cancelled = asyncio.Event()

        class WaitingModel(DraftModel):
            async def complete(self, system: str, messages: list[Message], tools: list[dict[str, object]]) -> ModelReply:
                try:
                    await asyncio.Event().wait()
                    raise AssertionError("unreachable")
                finally:
                    cancelled.set()

        enhancement = EmotionEnhancementRun(AgentSettings(timeout_seconds=0.01), "atri", WaitingModel(), "请润色原稿：")
        with pytest.raises(AgentError) as error:
            await enhancement.polish("原稿")
        assert error.value.code == "emotion_timeout"
        assert cancelled.is_set()
        assert request_purpose.get() == "chat" and preview_sink.get() is None

    asyncio.run(scenario())
