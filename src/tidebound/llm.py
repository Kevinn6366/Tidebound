"""Chat Completions 兼容模型适配，不承担 Agent 循环。"""

from typing import Protocol
from uuid import uuid4

import httpx
from pydantic import ValidationError

from src.tidebound.config import AgentSettings
from src.tidebound.debug import TerminalDebug
from src.tidebound.errors import AgentError
from src.tidebound.llm_stream import read_stream
from src.tidebound.runtime.types import Message, ModelReply, ToolCall
from src.tidebound.storage.model_requests import ModelRequestStore


def wire_messages(system: str, messages: list[Message]) -> list[dict[str, object]]:
    """在模型边界将内部消息转换成兼容接口结构。

    Args:
        system: 本次请求的角色提示词及有效的一次性工具规则。
        messages: 已完成预算选取的历史与本轮消息。

    Returns:
        保持工具调用 ID 关联的请求消息列表。
    """
    result: list[dict[str, object]] = [{"role": "system", "content": system}]
    for message in messages:
        item: dict[str, object] = {"role": message.role, "content": message.content}
        if message.role == "assistant" and message.reasoning_content is not None:
            item["reasoning_content"] = message.reasoning_content
        if message.tool_calls:
            item["tool_calls"] = [{"id": call.id, "type": "function", "function": {
                "name": call.name, "arguments": call.arguments,
            }} for call in message.tool_calls]
        if message.tool_call_id:
            item["tool_call_id"] = message.tool_call_id
        result.append(item)
    return result


class ModelClient(Protocol):
    """供循环与受控测试使用的唯一模型边界。"""

    async def complete(self, system: str, messages: list[Message], tools: list[dict[str, object]]) -> ModelReply:
        """根据角色、上下文和工具定义请求一次模型响应。"""
        ...


class ChatCompletionsClient:
    """每次请求独立连接，默认不重试或重定向携带凭据的请求。"""

    def __init__(self, settings: AgentSettings) -> None:
        self.settings = settings

    async def complete(self, system: str, messages: list[Message], tools: list[dict[str, object]]) -> ModelReply:
        """调用后端配置的模型并校验完整响应。

        Args:
            system: 本次请求的角色内容及有效的一次性注入。
            messages: 有效的本次调用消息。
            tools: 当前获准的工具定义。

        Returns:
            模型消息和结束原因。

        Raises:
            AgentError: 网络、供应商 HTTP 或响应协议错误；不回传原始响应。
            OSError: 完整请求快照写入失败，不继续发送请求。
        """
        headers = {"Content-Type": "application/json"}
        if self.settings.api_key.get_secret_value():
            headers["Authorization"] = f"Bearer {self.settings.api_key.get_secret_value()}"
        debug = TerminalDebug(self.settings.debug, f"LLM {uuid4().hex[:8]}")
        debug.write("请求", f"model={self.settings.model}, messages={len(messages)}, tools={len(tools)}\n")
        request = {"model": self.settings.model, "messages": wire_messages(system, messages),
                   "tools": tools, "tool_choice": "auto", "stream": self.settings.debug,
                   "max_tokens": self.settings.max_output_tokens}
        if self.settings.reasoning_effort is not None:
            request["reasoning_effort"] = self.settings.reasoning_effort
        snapshot = ModelRequestStore(self.settings.data_dir).save(request)
        if snapshot is not None:
            debug.write("完整请求", f"run={snapshot.run_id}, step={snapshot.step}, request={snapshot.request_id}（Console 查看）\n")
        try:
            async with httpx.AsyncClient(timeout=self.settings.timeout_seconds, trust_env=False) as client:
                url = self.settings.base_url.rstrip("/") + "/chat/completions"
                if self.settings.debug:
                    async with client.stream("POST", url, headers=headers, json=request) as response:
                        response.raise_for_status()
                        debug.write("连接", "HTTP 200，开始读取模型流\n")
                        return await read_stream(response, debug)
                response = await client.post(url, headers=headers, json=request)
                response.raise_for_status()
            payload = response.json()
            choice = payload["choices"][0]
            message = choice["message"]
            if message["role"] != "assistant":
                raise ValueError("unexpected role")
            if any(call.get("type") != "function" for call in message.get("tool_calls", [])):
                raise ValueError("unexpected tool type")
            calls = [ToolCall(id=call["id"], name=call["function"]["name"],
                              arguments=call["function"]["arguments"]) for call in message.get("tool_calls", [])]
            return ModelReply(message=Message(role="assistant", content=message.get("content") or "",
                                              reasoning_content=message.get("reasoning_content"), tool_calls=calls),
                              finish_reason=choice["finish_reason"])
        except httpx.HTTPStatusError as error:
            raise AgentError("model_http_error", f"模型服务返回 HTTP {error.response.status_code}，请检查服务端配置。", 502) from error
        except httpx.HTTPError as error:
            raise AgentError("model_connection_error", "无法连接模型服务或请求超时，请检查服务端配置。", 502) from error
        except (ValueError, KeyError, TypeError, IndexError, AttributeError, ValidationError) as error:
            raise AgentError("invalid_model_response", "模型服务返回了不支持的响应格式。", 502) from error
