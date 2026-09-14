"""轻量工具注册表：名称、参数模型和执行函数，不建设插件平台。"""
import json
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, ValidationError

from src.runtime.types import Message, ToolCall
from src.tools.current_time import get_current_time


class EmptyArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


@dataclass(frozen=True)
class Tool:
    """一个已注册能力的声明、输入校验和执行入口。"""

    name: str
    description: str
    arguments: type[BaseModel]
    execute: Callable[[BaseModel], object]

    def definition(self) -> dict[str, object]:
        """生成模型可见的函数声明，不包含执行函数本身。"""
        return {"type": "function", "function": {"name": self.name, "description": self.description,
                                                 "parameters": self.arguments.model_json_schema()}}


class ToolRegistry:
    """按名称查找与执行工具，普通失败转成对应调用的结果消息。"""

    def __init__(self, tools: list[Tool]) -> None:
        self._tools = {tool.name: tool for tool in tools}
        if len(self._tools) != len(tools):
            raise ValueError("工具名称重复")

    def definitions(self) -> list[dict[str, object]]:
        """返回此注册表允许向模型暴露的能力。"""
        return [tool.definition() for tool in self._tools.values()]

    def invoke(self, call: ToolCall) -> Message:
        """校验参数后执行工具，保持调用 ID 与结果关联。

        Args:
            call: 模型请求的工具名称、调用标识及 JSON 参数。

        Returns:
            成功或安全错误信息组成的 tool 消息，不抛出普通工具错误。
        """
        tool = self._tools.get(call.name)
        if tool is None:
            result: object = {"error": "unknown_tool", "message": "Tool is not registered."}
        else:
            try:
                args = tool.arguments.model_validate_json(call.arguments)
            except ValidationError:
                result = {"error": "invalid_arguments", "message": "Arguments do not match the tool schema."}
            else:
                try:
                    result = tool.execute(args)
                    # 检查结果可序列化；工具异常正文可能含外部数据，不直接回传。
                    json.dumps(result, allow_nan=False)
                except Exception:  # noqa: BLE001 - 工具边界将普通异常转换为模型可见错误
                    result = {"error": "tool_execution_failed", "message": "Tool execution failed."}
        return Message(role="tool", tool_call_id=call.id, content=json.dumps(result, ensure_ascii=False))


def create_tools(timezone: str) -> ToolRegistry:
    """组装首版允许的工具；新增能力只需在此注册。

    Args:
        timezone: 后端固定的时间工具时区。

    Returns:
        仅含当前时间工具的注册表。
    """
    return ToolRegistry([Tool("get_current_time", "获取当前日期和时间。", EmptyArguments,
                              lambda _: get_current_time(timezone))])
