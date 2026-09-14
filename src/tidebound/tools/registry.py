"""通过函数注册和调用工具，注册结果保存为普通字典。"""

import json
from collections.abc import Callable
from typing import NotRequired, TypedDict

from pydantic import BaseModel, ConfigDict, ValidationError

from src.tidebound.runtime.types import Message, ToolCall
from src.tidebound.tools.getcurrenttime.current_time import get_current_time


class EmptyArguments(BaseModel):
    """无参数工具的输入约束，拒绝额外字段。"""

    model_config = ConfigDict(extra="forbid", strict=True)


class ToolEntry(TypedDict):
    """注册字典的字段类型，仅用于类型检查，不封装工具行为。"""

    description: str
    injection: NotRequired[str]
    arguments: type[BaseModel]
    execute: Callable[[BaseModel], object]


ToolMap = dict[str, ToolEntry]


def register_current_time(tools: ToolMap, timezone: str) -> None:
    """向注册表添加当前时间工具，并绑定后端时区。

    Args:
        tools: 当前执行允许使用的工具字典。
        timezone: 后端配置的 IANA 时区名称，不允许模型覆盖。

    Raises:
        ValueError: 当前时间工具已经注册。
    """
    if "get_current_time" in tools:
        raise ValueError("工具名称重复：get_current_time")

    def execute(arguments: BaseModel) -> dict[str, str | float]:
        """查询配置时区的时间。

        Args:
            arguments: 已通过无参数校验的空对象。

        Returns:
            当前 ISO 时间、时区和 Unix 秒数。

        Raises:
            ZoneInfoNotFoundError: 部署环境不支持所配置的时区。
        """
        return get_current_time(timezone)

    tools["get_current_time"] = {
        "description": "获取当前日期和时间。",
        "injection": "tools.injection.timetools",
        "arguments": EmptyArguments,
        "execute": execute,
    }


def create_tools(timezone: str) -> ToolMap:
    """依次调用注册函数，创建本次使用的工具字典。

    Args:
        timezone: 后端配置的当前时间工具时区。

    Returns:
        按调用名称索引的工具字典。
    """
    tools: ToolMap = {}
    register_current_time(tools, timezone)
    return tools


def tool_definitions(tools: ToolMap) -> list[dict[str, object]]:
    """生成模型可见的工具声明。

    Args:
        tools: 当前执行允许使用的工具字典。

    Returns:
        包含名称、描述和参数格式的函数声明列表。
    """
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": tool["description"],
                "parameters": tool["arguments"].model_json_schema(),
            },
        }
        for name, tool in tools.items()
    ]


def invoke_tool(tools: ToolMap, call: ToolCall) -> Message:
    """校验并调用工具，将成功或安全错误结果关联到调用 ID。

    Args:
        tools: 当前执行允许使用的工具字典。
        call: 模型返回的工具名称、调用标识及 JSON 参数。

    Returns:
        工具结果消息，未知工具、非法参数及普通执行异常转为错误结果。
    """
    tool = tools.get(call.name)
    if tool is None:
        result: object = {"error": "unknown_tool", "message": "Tool is not registered."}
    else:
        try:
            args = tool["arguments"].model_validate_json(call.arguments)
        except ValidationError:
            result = {"error": "invalid_arguments", "message": "Arguments do not match the tool schema."}
        else:
            try:
                result = tool["execute"](args)
                # 提前检查序列化，避免工具返回非法结果导致整个执行中断。
                json.dumps(result, allow_nan=False)
            except Exception:  # noqa: BLE001 - 工具边界不公开可能包含敏感数据的异常正文
                result = {"error": "tool_execution_failed", "message": "Tool execution failed."}
    return Message(role="tool", tool_call_id=call.id, content=json.dumps(result, ensure_ascii=False))
