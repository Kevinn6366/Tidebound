"""通过函数注册和调用工具，注册结果保存为普通字典。"""

import inspect
import json
from collections.abc import Callable
from typing import NotRequired, TypedDict

from pydantic import BaseModel, ConfigDict, ValidationError

from src.tidebound.errors import AgentError
from src.tidebound.runtime.types import Message, ToolCall
from src.tidebound.tools.companion.arguments import (
    CancelFollowupArguments,
    CheckInterestArguments,
    CreateFollowupArguments,
    FactArguments,
    InterestArguments,
    ListFollowupsArguments,
    ReadPastArguments,
    SearchArguments,
    UpdateFollowupArguments,
    WeatherArguments,
    WebpageArguments,
)
from src.tidebound.tools.companion.operations import CompanionTools
from src.tidebound.tools.getcurrenttime.current_time import get_current_time
from src.tidebound.tools.internet.client import get_weather, read_webpage


class EmptyArguments(BaseModel):
    """无参数工具的输入约束，拒绝额外字段。"""

    model_config = ConfigDict(extra="forbid", strict=True)


class ToolEntry(TypedDict):
    """注册字典的字段类型，仅用于类型检查，不封装工具行为。"""

    description: str
    injection: NotRequired[str]
    tail_injection: NotRequired[str]
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


def tool_parameters(arguments: type[BaseModel]) -> dict[str, object]:
    """只向模型说明参数形状，完整校验约束保留在后端。

    Args:
        arguments: 执行时使用的完整参数模型。

    Returns:
        保留类型、参数名、必填项、枚举及默认值的紧凑 schema。
        长度、数值范围、重复描述等不进入模型请求。
    """
    return compact_schema(arguments.model_json_schema())


def compact_schema(schema: dict[str, object]) -> dict[str, object]:
    """递归压缩模型声明，不改变原 schema 或执行时的输入校验。

    Args:
        schema: Pydantic 生成的参数结构。

    Returns:
        保留调用形状、引用及分支的最小 JSON Schema。
    """
    result: dict[str, object] = {}
    for key, value in schema.items():
        if key in ('type', 'required', 'enum', 'const', 'default', '$ref'):
            result[key] = value
        elif key in ('properties', '$defs') and isinstance(value, dict):
            result[key] = {name: compact_schema(child) for name, child in value.items()}
        elif key in ('anyOf', 'oneOf', 'allOf') and isinstance(value, list):
            result[key] = [compact_schema(child) for child in value]
        elif key == 'items' and isinstance(value, dict):
            result[key] = compact_schema(value)
    return result


class ToolRequest(BaseModel):
    """统一入口信封；业务参数由被选中的工具再次严格校验。"""

    model_config = ConfigDict(extra='forbid', strict=True)
    name: str
    arguments: str | dict[str, object]


def tool_definitions(tools: ToolMap) -> list[dict[str, object]]:
    """用自然语言能力目录和单一调用入口替代全量工具 schema。

    Args:
        tools: 本轮实际获准的能力，未授权工具不进入目录。

    Returns:
        一个 use_tool 声明；空注册表返回空列表。
    """
    if not tools:
        return []
    catalog = []
    for name, tool in tools.items():
        schema = tool_parameters(tool['arguments'])
        required = schema.get('required', [])
        parameters = []
        for field, shape in schema.get('properties', {}).items():
            hint = '|'.join(str(value) for value in shape['enum']) if 'enum' in shape else ''
            parameters.append(field + ('?' if field not in required else '') + (':' + hint if hint else ''))
        catalog.append(f"{name}({','.join(parameters)})：{tool['description']}")
    example = ('name=search_web，arguments=\"{\\\"query\\\":\\\"Python 最新版本\\\"}\"。'
               if 'search_web' in tools else '无参数调用的 arguments 填 \"{}\"。')
    return [{'type': 'function', 'function': {
        'name': 'use_tool',
        'description': '按需使用能力：name 填能力名，arguments 填 JSON 对象字符串（不是 XML）。' + example + '? 表示可省略；offset/limit 为整数，经纬度为数值，其余为字符串。\n' + '\n'.join(catalog),
        'parameters': {'type': 'object', 'properties': {
            'name': {'type': 'string'}, 'arguments': {'type': 'string', 'description': '业务参数的 JSON 对象字符串；无参数时填 {}。'}},
            'required': ['name', 'arguments'], 'additionalProperties': False},
    }}]


def resolve_tool_call(call: ToolCall) -> ToolCall | None:
    """解包统一入口，保留调用 ID，兼容既有直接调用记录。

    Args:
        call: 模型返回的调用信封。

    Returns:
        实际业务调用；信封不合法时返回 None。不会递归解析嵌套入口。
    """
    if call.name != 'use_tool':
        return call
    try:
        request = ToolRequest.model_validate_json(call.arguments)
    except ValidationError:
        return None
    return ToolCall(id=call.id, name=request.name, arguments=request.arguments if isinstance(request.arguments, str)
                    else json.dumps(request.arguments, ensure_ascii=False))


def argument_failure(error: ValidationError, schema: type[BaseModel]) -> dict[str, object]:
    """返回可纠正的字段诊断，不包含输入值、额外字段名或异常原文。

    Args:
        error: 完整业务参数校验错误。
        schema: 当前工具允许的参数模型。

    Returns:
        安全错误码与字段错误类型列表。
    """
    fields = set(schema.model_fields)
    issues = []
    for item in error.errors(include_input=False, include_context=False, include_url=False)[:8]:
        location = item['loc']
        field = str(location[0]) if location and location[0] in fields else 'arguments'
        issues.append({'field': field, 'reason': item['type']})
    required = [name for name, field in schema.model_fields.items() if field.is_required()]
    return {'error': 'invalid_arguments', 'message': '请按必填字段重试，arguments 使用合法 JSON 对象字符串。',
            'required': required, 'issues': issues}


def invoke_tool(tools: ToolMap, call: ToolCall) -> Message:
    """校验并调用工具，将成功或安全错误结果关联到调用 ID。

    Args:
        tools: 当前执行允许使用的工具字典。
        call: 模型返回的工具名称、调用标识及 JSON 参数。

    Returns:
        工具结果消息，未知工具、非法参数及普通执行异常转为错误结果。
    """
    resolved = resolve_tool_call(call)
    if resolved is None:
        return Message(role='tool', tool_call_id=call.id,
                       content=json.dumps({'error': 'invalid_arguments', 'message': 'name 必须为能力名，arguments 必须为 JSON 对象字符串，例如 {"query":"搜索词"}；不要输出 XML 标签。'}))
    call = resolved
    tool = tools.get(call.name)
    if tool is None:
        result: object = {"error": "unknown_tool", "message": "Tool is not registered."}
    else:
        try:
            args = tool["arguments"].model_validate_json(call.arguments)
        except ValidationError as error:
            result = argument_failure(error, tool["arguments"])
        else:
            try:
                result = tool["execute"](args)
                # 提前检查序列化，避免工具返回非法结果导致整个执行中断。
                json.dumps(result, allow_nan=False)
            except Exception:  # noqa: BLE001 - 工具边界不公开可能包含敏感数据的异常正文
                result = {"error": "tool_execution_failed", "message": "Tool execution failed."}
    return Message(role="tool", tool_call_id=call.id, content=json.dumps(result, ensure_ascii=False))


def register_companion_tools(tools: ToolMap, service: 'CompanionTools', *, internet_enabled: bool) -> None:
    """绑定当前 Run 的陪伴业务入口，仅在授权联网时注册现实信息工具。

    Args:
        tools: 本次执行独有的注册表。
        service: 运行时构造的有效历史、状态与工作流服务。
        internet_enabled: 用户发送本轮消息时明确开启的联网权限。
    """
    tools['read_conversation_summary'] = {
        'description': '读取长期对话摘要：共同经历、关系变化、话题与约定；含覆盖时间，细节可回看原文。',
        'arguments': EmptyArguments, 'execute': lambda _: service.read_conversation_summary(),
    }
    register_read_past_conversation(tools, service)
    register_remember_fact(tools, service)
    register_create_followup(tools, service)
    register_list_followups(tools, service)
    register_update_followup(tools, service)
    register_cancel_followup(tools, service)
    if internet_enabled:
        register_search_web(tools, service)
        register_read_webpage(tools, service)
        register_get_weather(tools, service)
        register_save_interest(tools, service)
        register_check_interest_updates(tools, service)


def register_read_past_conversation(tools: ToolMap, service: CompanionTools) -> None:
    """注册 read_past_conversation 并绑定当前执行业务范围。

    Args:
        tools: 本次已授权工具字典。
        service: 当前账号和 Run 的业务入口。
    """
    tools['read_past_conversation'] = {'description': '回看历史对话。', 'arguments': ReadPastArguments,
                       'execute': service.read_past}


def register_remember_fact(tools: ToolMap, service: CompanionTools) -> None:
    """注册 remember_fact 并绑定当前执行业务范围。

    Args:
        tools: 本次已授权工具字典。
        service: 当前账号和 Run 的业务入口。
    """
    tools['remember_fact'] = {'description': '记住用户明确的事实。', 'arguments': FactArguments,
                       'execute': service.remember}


def register_create_followup(tools: ToolMap, service: CompanionTools) -> None:
    """注册 create_followup 并绑定当前执行业务范围。

    Args:
        tools: 本次已授权工具字典。
        service: 当前账号和 Run 的业务入口。
    """
    tools['create_followup'] = {'description': '记下以后要关心的事。', 'arguments': CreateFollowupArguments,
                       'execute': service.change_followup}


def register_list_followups(tools: ToolMap, service: CompanionTools) -> None:
    """注册 list_followups 并绑定当前执行业务范围。

    Args:
        tools: 本次已授权工具字典。
        service: 当前账号和 Run 的业务入口。
    """
    tools['list_followups'] = {'description': '查看待关心的事。', 'arguments': ListFollowupsArguments,
                       'execute': service.list_followups}


def register_update_followup(tools: ToolMap, service: CompanionTools) -> None:
    """注册 update_followup 并绑定当前执行业务范围。

    Args:
        tools: 本次已授权工具字典。
        service: 当前账号和 Run 的业务入口。
    """
    tools['update_followup'] = {'description': '更新事情的进展或结束状态。', 'arguments': UpdateFollowupArguments,
                       'execute': service.change_followup}


def register_cancel_followup(tools: ToolMap, service: CompanionTools) -> None:
    """注册 cancel_followup 并绑定当前执行业务范围。

    Args:
        tools: 本次已授权工具字典。
        service: 当前账号和 Run 的业务入口。
    """
    tools['cancel_followup'] = {'description': '取消不再想聊的事。', 'arguments': CancelFollowupArguments,
                       'execute': service.change_followup}


def register_search_web(tools: ToolMap, service: CompanionTools) -> None:
    """注册 search_web 并绑定当前执行业务范围。

    Args:
        tools: 本次已授权工具字典。
        service: 当前账号和 Run 的业务入口。
    """
    tools['search_web'] = {'description': '上网了解话题，返回阅读印象。',
                       'tail_injection': 'tools.injection.websearch', 'arguments': SearchArguments,
                       'execute': service.search}


def register_read_webpage(tools: ToolMap, service: CompanionTools) -> None:
    """注册 read_webpage 并绑定当前执行业务范围。

    Args:
        tools: 本次已授权工具字典。
        service: 当前账号和 Run 的业务入口。
    """
    tools['read_webpage'] = {'description': '阅读指定网页。', 'arguments': WebpageArguments,
                       'execute': lambda a: read_webpage(a.url)}


def register_get_weather(tools: ToolMap, service: CompanionTools) -> None:
    """注册 get_weather 并绑定当前执行业务范围。

    Args:
        tools: 本次已授权工具字典。
        service: 当前账号和 Run 的业务入口。
    """
    tools['get_weather'] = {'description': '了解指定地点的天气。', 'arguments': WeatherArguments,
                       'execute': lambda a: get_weather(a.location, a.latitude, a.longitude)}


def register_save_interest(tools: ToolMap, service: CompanionTools) -> None:
    """注册 save_interest 并绑定当前执行业务范围。

    Args:
        tools: 本次已授权工具字典。
        service: 当前账号和 Run 的业务入口。
    """
    tools['save_interest'] = {'description': '记下用户感兴趣的话题。', 'arguments': InterestArguments,
                       'execute': service.save_interest}


def register_check_interest_updates(tools: ToolMap, service: CompanionTools) -> None:
    """注册 check_interest_updates 并绑定当前执行业务范围。

    Args:
        tools: 本次已授权工具字典。
        service: 当前账号和 Run 的业务入口。
    """
    tools['check_interest_updates'] = {'description': '看看已关注的话题有什么新动静。',
                       'tail_injection': 'tools.injection.websearch', 'arguments': CheckInterestArguments,
                       'execute': service.interest_updates}


async def invoke_tool_async(tools: ToolMap, call: ToolCall) -> Message:
    """校验并执行同步或异步工具，不把停止控制包装成普通工具错误。

    Args:
        tools: 当前执行经过授权的注册表。
        call: 模型提出的调用及参数。

    Returns:
        关联调用 ID 的安全结果，异常不泄漏凭据和第三方响应。

    Raises:
        AgentError: 整轮停止控制必须交回运行时。
        CancelledError: 任务取消不能被工具吞掉。
    """
    resolved = resolve_tool_call(call)
    if resolved is None:
        return Message(role='tool', tool_call_id=call.id,
                       content=json.dumps({'error': 'invalid_arguments', 'message': 'name 必须为能力名，arguments 必须为 JSON 对象字符串，例如 {"query":"搜索词"}；不要输出 XML 标签。'}))
    call = resolved
    tool = tools.get(call.name)
    if tool is None:
        result: object = {'error': 'unknown_tool', 'message': 'Tool is not registered.'}
    else:
        try:
            args = tool['arguments'].model_validate_json(call.arguments)
        except ValidationError as error:
            result = argument_failure(error, tool['arguments'])
        else:
            try:
                result = tool['execute'](args)
                if inspect.isawaitable(result):
                    result = await result
                json.dumps(result, allow_nan=False)
            except AgentError as error:
                if error.code == 'run_stopped':
                    raise
                result = {'error': error.code, 'message': str(error) if error.code == 'invalid_evidence' else 'Tool workflow failed.'}
            except Exception:  # noqa: BLE001 - 不公开网络凭据或用户资料
                result = {'error': 'tool_execution_failed', 'message': 'Tool execution failed.'}
    return Message(role='tool', tool_call_id=call.id, content=json.dumps(result, ensure_ascii=False))
