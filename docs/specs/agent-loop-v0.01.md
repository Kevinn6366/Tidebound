# Agent loop v0.01

日期：2026-09-14。用户最新确认的首版交付覆盖本文件与旧规格冲突的范围：前后端固定 atri，整个 `prompts/` 是亚托莉的一套提示词，后续通过替换整个目录替换内容；当前只有 `chat.character`。旧 `characters/atri`、`shared`、`workflows/summary` 的提示词目录划分废止。

## 最小闭环

参考 Pi 的 agent core 循环与 coding-agent 会话层分离：应用层管理执行和历史，循环只做模型调用、工具执行和结果回填。使用 Python 普通异步函数，不依赖 Pi TypeScript 包或 Agent 编排框架，不迁移 coding-agent 的文件、终端、技能、队列或压缩机制。

- 固定角色 `atri` / 亚托莉，前端不能提交角色、历史、提示词或模型密钥。
- 当前仅文本输入，附件明确返回未支持；模型通过服务端配置的 Chat Completions 兼容接口调用，缺失配置明确报错。
- 唯一工具 `get_current_time`，无参数，返回配置时区的 ISO 时间、时区与 Unix 时间戳。工具名称、参数对象和允许字段由代码检查。
- 工具调用消息与结果追加到本次执行的消息中，再次调用模型；无工具调用且正常返回正文时完成。截断、异常、超时或调用次数超限均失败，不把中间文本当作最终回复。
- 最多 4 次模型调用，每批最多 8 个工具调用，模型输出预留默认 2,048 tokens，总执行超时默认 120 秒；这些是 v0.01 可配置保护值，不是未来材料预算分配算法。
- 上下文保留角色提示词、本轮消息与装得下的最近完整已提交轮次。使用请求 JSON 的 UTF-8 字节数加格式余量保守约束 byte-tokenizer 兼容请求；这不是供应商精确计费统计。复杂材料配额、summary 与场景注入仍由未来 issue #1 跟踪。

## 工具边界（采纳酒馆的五项设计）

工具注册表按名称保存声明、参数模型和执行函数。新增工具只修改注册入口，不修改主循环。`src/tools/registry.py` 负责查找、参数校验和执行；`src/runtime/agent_loop.py` 控制模型继续回答及停止条件。

每个调用通过 `tool_call_id` 关联结果。未知工具、非法参数或普通执行异常转成工具错误消息，模型下一次调用可据此调整；失败原始异常不直接公开。运行协议错误、停止、超时、轮数上限属于整轮控制，不能包装成普通工具错误后无限继续。

已完成的调用链随聊天历史保存并传回模型。页面 Log 中另提供工具记录折叠区，展示名称、参数、结果和该轮是否提交；停止或失败的记录可检查，但不进入有效模型历史。首版仅提供注册机制，尚无动态插件加载。

## 运行和提交

首版明确限定本地单进程、单 worker 的 dev 验收，不开放生产模式。沿用开发浏览器 Cookie 作为会话范围，不能将它宣称为账号认证。每个范围只有一个长期 atri 会话，同时仅允许一个 Run；重复 run ID 不重复执行。

首版用 `data/agent/<scope>/<run-id>.json` 原子写入执行记录；不新增另一种数据库，也不宣称 MySQL 生产持久化已完成。只有 completed 记录中的消息进入后续历史。成功时一次提交用户输入、工具调用与结果以及最终回复；失败和停止保留审计记录，但不进入有效历史。重启时将遗留的 running 记录标记为 interrupted，不自动重放。

HTTP 提交返回 Run ID，浏览器查询状态；刷新或断线不等同于停止。停止指定 Run 时撤销其提交资格，回到该 Run 开始前的已提交历史，本次用户输入也不提交。完成与停止以服务端先完成的状态变更为准。旧停止请求不能停止较新的 Run。

旧 UI 存读档保留为展示资料，不能改变模型会话；用户新建/切换会话和管理员回退均不在首版实现范围，不用前端历史替代服务端事实。

## Prompt manifest

参考用户指定的 `takecopter-prompts/prompts` 组织：`prompts/master.yaml` 内为 `prompts → chat.character → language → variants → name/segments`，内容引用 `@master/chat.character/chat.character-zh.md`。不接入 Bamfly/Heathrow、Nelu 远端或模型配置引用机制。

内容使用静态 Markdown；支持去除 Go 模板风格的版本注释，其他模板指令首版明确拒绝，避免把未执行的模板发送给模型。加载器校验 manifest、唯一名称、文件引用和路径范围，依次拼接 segments。运行开始时加载一次，整轮使用同一份内容；替换目录后从下一轮生效。

## 验证范围

验证正常回复、真实本地时间工具、工具结果回填、未知/非法工具、截断和循环上限、模型协议错误、超时、重复提交、并发拒绝、停止竞争、重启恢复、历史隔离、整目录替换与 manifest 错误。使用本地模型协议测试服务验证前后端完整链路；该服务不代表真实模型质量。真实供应商验收需要配置可用模型。

参考：[Pi agent-loop](https://github.com/badlogic/pi-mono/blob/main/packages/agent/src/agent-loop.ts)、[Pi coding-agent session](https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/src/core/agent-session.ts)。

## 本地终端 debug

`TIDEBOUND_DEBUG=true` 时使用模型 SSE 输出，在后端终端实时展示供应商返回的 `reasoning_content`、回复及工具调用，标记请求与执行状态；关闭时继续使用非流式接口。不会为不返回思考字段的模型伪造思考文本。终端调试输出不代表完成提交，缺失结束标记、流错误、停止或超时仍按失败/停止处理。

模型返回的思考字段随 assistant 消息保存在本地执行记录中，并在后续模型调用时按协议回传，也计入上下文预算；用户页面的正式回复仍只取 `content`。请求头、API Key 和完整请求提示词不写入调试输出。GLM-5.3 推理强度可通过可选的 `TIDEBOUND_LLM_REASONING_EFFORT` 配置。

参考：[智谱思考模式](https://docs.bigmodel.cn/cn/guide/capabilities/thinking-mode)、[流式工具输出](https://docs.bigmodel.cn/cn/guide/capabilities/stream-tool)。
