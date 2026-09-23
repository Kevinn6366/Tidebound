# AGENTS.md

## Tidebound 开发指引

先阅读 [宏观架构规格](docs/specs/architecture.md)，再阅读 `docs/specs/` 中与当前任务有关的专项规格。历史讨论保存在 `docs/architecture/discussions/`，以当前有效规格和用户最新确认的要求为准。

- Web 前端放在 `webfrontend/`，FastAPI 通信层放在 `webapp/`，Agent 业务内核放在 `src/tidebound/`；`legacy/gwcpro/` 保留尚未迁移的上游业务，禁止从新应用导入旧 Agent。前端交互的服务端通信、输入校验、展示转换、日志读取和界面资源存储全部放在 `webapp/`，执行委托 `src/tidebound/runtime/`；不再保留根目录 `backend/`。
- 展示与通信迁移状态、验收范围见 `docs/specs/web-migration.md`；`webfrontend/src/gwc/` 保留完整上游界面与设置，模型执行已移除；`webfrontend/legacy/` 是原始参考，不进入构建或静态发布。
- FastAPI 负责通信适配；Agent 执行与会话协调归 `src/tidebound/runtime/`，上下文、记忆、工作流、工具和存储按架构规格分别实现。
- 账号与管理员 console 的认证、登录会话及权限检查统一放在 `webapp/auth/`，不得放在 `backend/`；MySQL 和日志范围见 `docs/specs/accounts-and-console.md`。
- 提示词内容统一放在 `prompts/`；凭据与运行数据不进入版本控制。
- 实现须遵守用户隔离、停止、历史回退、旧结果提交和外部副作用边界，具体语义以对应规格为准。
- 当前空目录只表示职责归属。未定的协议、依赖、部署方式和未来能力在专项规格明确后再实现；只声明实际完成并验证的能力。

---

本文件规定本仓库中所有 Agent 进行 Python、WebApp、Agent Runtime 和前端开发时必须遵循的工程规范。

除非子目录存在更具体的 `AGENTS.md`，否则本规范适用于整个仓库。

`MUST` 表示必须遵守，`SHOULD` 表示原则上应遵守。

---

## Git 分支与提交

- 小改动完成必要验证后，Agent MUST 自行提交到 `dev` 分支，无需再次询问。提交前检查当前分支与暂存差异，只提交本次任务相关文件或改动，不夹带其他未完成工作、凭据或运行数据。
- `main` 和 `prod` 是生产环境分支，严禁向这两个分支提交、合并或推送。不得通过切换分支、重置或强制推送绕过此限制。
- 当前不在 `dev` 时，先在保留已有工作的前提下准备 `dev` 工作区，再执行提交；不得丢弃用户或其他任务的改动。自行提交不等于获准部署或推送远端。

## 1. 基本原则

代码 MUST 优先保证：

* 正确性；
* 可读性；
* 可维护性；
* 类型安全；
* 职责清晰；
* 最小必要复杂度。

优先使用简单、直接、容易理解的实现。

MUST NOT 为尚未存在的需求提前引入复杂抽象、基础设施或重型依赖。

修改现有代码时，应遵循当前项目架构和命名习惯，避免无关重构。

---

## 2. 函数设计

每个函数 SHOULD 只承担一个逻辑完整的职责。

如果一个函数同时负责数据库、网络请求、业务逻辑、数据转换、UI 等多个阶段，应拆分为独立函数或模块。

推荐：

```python
validate_request(...)
load_runtime_context(...)
build_agent_input(...)
execute_agent(...)
persist_message(...)
```

不推荐将上述逻辑全部塞入一个数百行的 `process()` 或 `handle()`。

函数和变量名称 MUST 表达实际意图。

推荐：

```python
load_session()
build_prompt()
execute_agent()
persist_tool_result()
```

避免：

```python
handle()
process()
do()
helper()
manage()
```

---

## 3. Python 函数规范

Python 新代码 MUST 使用类型标注。

```python
async def load_session(session_id: str) -> Session:
    ...
```

非简单函数 MUST 使用 Google Style Docstring，说明文字统一使用中文。

标准格式：

```python
async def load_runtime_context(
    session_id: str,
    include_tool_messages: bool = True,
) -> RuntimeContext:
    """
    加载指定会话的完整 Agent Runtime 上下文。

    Args:
        session_id: 需要加载的长期会话唯一标识符。
        include_tool_messages: 是否包含历史工具调用及工具返回消息。

    Returns:
        已完成标准化处理的 RuntimeContext。

    Raises:
        SessionNotFoundError: 当指定会话不存在时抛出。
        RuntimeContextError: 当历史消息无法转换为合法上下文时抛出。
    """
```

Docstring MUST 说明：

* 函数的实际职责；
* 每个业务参数的含义；
* 返回值含义；
* 重要异常。

禁止仅重复变量名：

```python
Args:
    session_id: session id。
```

应说明业务语义：

```python
Args:
    session_id: 当前用户长期会话的唯一标识符。
```

---

## 4. JavaScript / TypeScript 函数规范

前端新增业务代码 SHOULD 优先使用 TypeScript。

非简单函数 MUST 使用 JSDoc，说明文字统一使用中文。

标准格式：

```ts
/**
 * 加载指定会话的完整 Runtime 上下文。
 *
 * @param sessionId - 需要加载的长期会话唯一标识符。
 * @returns 会话元数据以及已经持久化的历史消息。
 * @throws 当指定会话不存在时抛出 SessionNotFoundError。
 */
async function loadRuntimeContext(
  sessionId: string,
): Promise<RuntimeContext> {
  ...
}
```

所有业务参数 MUST 有对应的 `@param`。

导出函数 MUST 显式声明返回类型。

```ts
export async function loadSession(
  sessionId: string,
): Promise<Session> {
  ...
}
```

禁止无理由使用 `any`。外部未知数据优先使用 `unknown`，并进行 Schema 校验或类型收窄。

---

## 5. 参数设计

避免含义不明确的布尔参数。

不推荐：

```ts
loadMessages(sessionId, true, false);
```

推荐：

```ts
loadMessages(sessionId, {
  includeToolMessages: true,
  includeSystemMessages: false,
});
```

当函数参数较多或属于同一业务配置时，SHOULD 使用结构化参数对象。

---

## 6. API 与业务逻辑

FastAPI Route、HTTP Handler、WebSocket Handler MUST 保持轻量。

接口层主要负责：

1. 接收和校验请求；
2. 调用 Application / Service；
3. 返回响应。

业务逻辑 MUST NOT 大量堆积在接口层。

推荐：

```python
@router.post("/messages")
async def create_message(
    request: CreateMessageRequest,
) -> CreateMessageResponse:
    """
    接收用户消息并启动一次 Agent 消息处理流程。

    Args:
        request: 已完成结构校验的消息创建请求。

    Returns:
        包含最终 Assistant 消息的接口响应。
    """
    message = await chat_service.process_user_message(request)
    return CreateMessageResponse(message=message)
```

数据库访问 SHOULD 集中在 Repository 或数据访问层。

Agent Runtime SHOULD 与 HTTP、WebSocket、UI 和具体数据库实现解耦。

推荐依赖方向：

```text
UI / API
   ↓
Application Service
   ↓
Agent Runtime / Domain
   ↓
Repository / Infrastructure
```

---

## 7. React / Web 前端

React Component SHOULD 主要负责：

* UI 渲染；
* UI 状态；
* 用户交互编排。

复杂业务逻辑 SHOULD 放入：

* hooks；
* services；
* stores；
* domain modules；
* API client。

组件中避免到处直接调用：

```ts
fetch(...)
```

网络访问 SHOULD 集中在 API Client 层。

例如：

```ts
/**
 * 向服务端发送新的用户消息。
 *
 * @param input - 创建消息所需要的会话和正文信息。
 * @returns 服务端返回的消息处理结果。
 * @throws 当请求失败或响应数据非法时抛出 ApiError。
 */
export async function createMessage(
  input: CreateMessageInput,
): Promise<CreateMessageResult> {
  const response = await apiClient.post("/messages", input);
  return createMessageSchema.parse(response.data);
}
```

简单的一行事件无需强制写完整 JSDoc。

```tsx
<button onClick={() => setOpen(true)}>
```

但涉及 API、状态同步、数据转换、WebSocket 或业务逻辑的函数必须写说明。

---

## 8. 异常处理

MUST NOT 静默吞异常。

禁止：

```python
try:
    await save_message(message)
except Exception:
    pass
```

异常应：

* 被明确处理；
* 转换为领域异常；
* 或继续向上抛出。

错误信息 SHOULD 包含有助于定位问题的上下文，但 MUST NOT 输出密码、Token、API Key、Cookie 等敏感信息。

---

## 9. 注释规范

注释 SHOULD 解释“为什么这样做”，而不是逐行翻译代码。

不推荐：

```python
# retry_count 加一
retry_count += 1
```

推荐：

```python
# 工具调用与模型调用采用独立重试额度，
# 避免工具故障消耗模型请求的重试次数。
retry_count += 1
```

MUST NOT 长期保留已经注释掉的旧代码，历史版本由 Git 管理。

完全显然的一行函数、回调和 getter 无需为了形式完整而添加冗余文档。

---

## 10. 常量与类型

业务逻辑中 SHOULD 避免无法解释的 Magic Number。

不推荐：

```python
if retry_count >= 3:
```

推荐：

```python
MAX_AGENT_RETRY_COUNT = 3

if retry_count >= MAX_AGENT_RETRY_COUNT:
```

稳定存在的业务概念 SHOULD 定义明确的数据类型或模型，而不是长期传递无结构的 `dict`、`object` 或 `any`。

---

## 11. Agent 修改代码规则

Agent 修改代码时 MUST：

1. 先阅读目标代码及相关调用关系；
2. 沿用现有架构和公共接口；
3. 只修改完成当前任务必要的代码；
4. 避免无关重构、重命名和格式化；
5. 新增非简单函数时补充完整 Docstring / JSDoc；
6. 修改已有函数时，如果该函数缺少必要文档，应同时补充；
7. 不得因为发现其他旧代码不符合规范而主动进行全仓库清理。

遵循：

> Touch it, improve it.

而不是：

> See it, refactor it.

---

## 12. 参考实现

### Python

```python
async def send_message(
    request: SendMessageRequest,
) -> SendMessageResult:
    """
    处理用户消息并协调完整的 Agent 执行流程。

    该函数只负责编排会话加载、Agent 执行和消息持久化，
    不直接实现数据库、Prompt 或模型调用细节。

    Args:
        request: 已完成接口层校验的用户消息请求。

    Returns:
        包含用户消息和 Assistant 消息的处理结果。

    Raises:
        SessionNotFoundError: 当目标会话不存在时抛出。
        AgentExecutionError: 当 Agent 无法正常完成执行时抛出。
    """
    context = await load_runtime_context(request.session_id)

    result = await agent_runtime.execute(
        build_runtime_input(
            context=context,
            content=request.content,
        )
    )

    return await persist_agent_result(
        session_id=request.session_id,
        result=result,
    )
```

### TypeScript

```ts
/**
 * 向服务端发送用户消息并返回本次 Agent 执行结果。
 *
 * @param input - 用户消息请求参数。
 * @param input.sessionId - 当前长期会话的唯一标识符。
 * @param input.content - 用户输入的消息正文。
 * @returns 服务端持久化后的消息结果。
 * @throws 当网络请求失败或返回数据非法时抛出 ApiError。
 */
export async function sendMessage(
  input: SendMessageInput,
): Promise<SendMessageResult> {
  const response = await apiClient.post(
    "/api/messages",
    input,
  );

  return sendMessageResultSchema.parse(response.data);
}
```
