# 账号鉴权与日志 Console

日期：2026-09-14。依据用户本轮确认，Agent 内核统一迁入 `src/tidebound/`，新增简单账号鉴权，管理员 console 提供“查看完整 LLM 对话上下文”和“查看日志”两个独立入口。

## 目录与运行范围

`src/tidebound/` 包含 runtime、context、tools、storage、memory、workflows、sandbox，以及模型、提示词加载、配置、错误和调试模块。memory、workflows、sandbox 仍为空职责目录，不表示能力已实现。根目录 `backend/` 负责应用编排与展示转换，`webapp/` 负责 FastAPI 通信。

当前仍是本地单进程、单 worker dev。账号改为 MySQL 持久化；聊天执行记录仍按内部归属 UUID 保存于 `data/agent/<scope>/`。不自动将旧匿名 Cookie 的历史绑定到新账号。

## 账号与会话

- UID 从 `uid-00000001` 递增，首个账号 `admin` 为管理员。密码由用户指定，代码与文档不保存明文。
- 用户角色只有 `user`、`admin`。首次初始化仅允许本机且仅可执行一次；之后注册均为普通用户，客户端不能提交角色或 UID。
- `src/tidebound/storage/users.py` 用参数化 SQL 读写 MySQL `users` 表，保存 UID、用户名、角色、内部 scope、随机盐及 PBKDF2 SHA-256 密码哈希。数据库故障明确返回错误，不回退到 JSON 或 SQLite。
- 登录产生 24 小时有效的随机会话，使用 HttpOnly、SameSite=Strict Cookie；HTTPS 下启用 Secure。会话暂存服务端内存，服务重启后重新登录，账号和用户数据保留。
- 每次请求从服务端账号记录验证身份与角色。URL、请求头和前端缓存不能授权访问其他账号。跨来源写入被拒绝。
- 同一账号在不同浏览器共享自己的会话历史与设置；旧 UI 的 `preview` 仅作为“当前已登录账号”的兼容别名，不是匿名访问入口。

## 页面与 API

| 入口 | 行为 |
| --- | --- |
| `/app/` | 未登录显示登录/注册页；已登录跳转至自己的 UID 入口 |
| `/app/{uid}` | 仅登录账号自己的对话页面 |
| `/app/{uid}/console` | 仅当前管理员自己的 console 页面 |
| `GET /api/auth/status` | 是否需要首次初始化 |
| `POST /api/auth/setup` | 本机首次创建管理员并登录 |
| `POST /api/auth/register` | 创建普通账号并登录 |
| `POST /api/auth/login` | 用户名和密码登录 |
| `GET /api/auth/me` | 返回当前账号 UID、名称和角色 |
| `POST /api/auth/logout` | 撤销会话并清除 Cookie |
| `GET /api/users/{uid}/console/log` | 管理员读取固定日志末尾 100 行 |
| `GET /api/users/{uid}/console/requests?offset=0` | 兼容的平铺请求摘要接口，每页 50 条 |
| `GET /api/users/{uid}/console/request-runs?offset=0` | 按对话分组分页，每页 50 轮，每组保留全部请求子菜单 |
| `GET /api/users/{uid}/console/requests/{request_id}` | 管理员读取一次模型请求的完整正文 |

聊天、设置和资源写入 API 必须登录；普通用户不能调用管理员 API。匿名请求返回 401，角色或 UID 不匹配返回 403。旧业务能力仍不转发到 legacy 后端。

## 完整 LLM 对话上下文

进入 console 先展示两个选择，只有选中的查看区加载和刷新。上下文区先按一次用户输入对应的 Run 展示对话列表，以本轮问题为标题；进入一轮后，通过“第 1 次发送给 LLM”“第 2 次发送给 LLM”等子菜单选择。一次对话无论调用模型多少次都为一组，按组分页，不拆散调用链。每两秒串行刷新，已选正文不会被新请求自动替换。

正文按消息顺序和 role 分段展示，保留换行，每条消息可点击标题折叠；提供一键折叠/展开本轮输入之前历史消息的按钮，system 和本轮消息不受批量折叠影响；工具调用、工具结果与思考字段可检查，另保留完整原始 JSON 和工具声明。新增快照单独记录本次一次性注入正文，有注入时显示具体规则，无注入时隐藏该区域；此字段是审计元数据，不添加到模型请求。旧快照缺少该字段时明确标记未知，不能据此判断没有注入。

在模型适配器构造完最终 HTTP JSON 正文之后、发送之前，保存同一份正文到 `TIDEBOUND_AGENT_DATA_DIR/model-requests/<request-id>.json`，默认位于 `data/agent/model-requests/`。包含实际裁剪后的消息、system 中本次有效的一次性注入、历史思考字段（如有）、工具调用及结果、tools 声明和模型参数。记录不依赖 `TIDEBOUND_DEBUG`，流式和非流式都支持；不包含 HTTP 请求头、Authorization、Cookie 或后端凭据配置。

快照标注所属账号内部 scope、Run ID、调用次数、创建时间和请求 ID。它记录发送前的请求尝试，不证明供应商已经接收；失败与停止也不会删除已经产生的快照。文件原子写入，无法保存时不继续发送未记录的请求。服务重启后可以读取已有记录，新增功能以前的请求没有快照，不能从当前提示词伪造重建。

全文通过单独接口读取，不受日志 100 行或 256 KiB 限制；摘要分页返回，不在轮询时重复传输正文。管理员范围沿用统一开发日志，可检查服务内所有账号，普通用户不能访问，响应禁止缓存，前端用纯文本 JSON 展示。路径只由后端目录与校验后的 UUID 构造。

这些快照属于管理员审计数据，不进入聊天消息或有效历史；一次性注入可在快照中检查，但不会因此在下一轮重新注入。当前不提供自动清理或精确请求重放。

## 日志边界

Console 对应 `tail -n 100 -f data/agent-debug.log` 的页面版本，每秒串行读取一次文件尾部，默认自动滚动，单次最多读 256 KiB；支持日志追加、截断、文件轮换和暂未创建状态。文件路径固定在后端，客户端不能选择其他路径。文本按纯文本渲染，响应禁止缓存。

当前按用户最新要求读取开发服务的统一日志文件，不从 Run JSON 重建日志，也不声称该文件已经按用户过滤。普通用户不能读取它。新一轮执行只有写入此文件后才会出现在 console；使用重定向启动开发服务，并关闭 HTTP access log，避免轮询请求刷满日志。

## 本地运行

1. `uv sync` 安装依赖，在 `.env` 配置模型以及 `TIDEBOUND_MYSQL_*` 参数；数据库密码与 root 密码分别设置。
2. `docker compose --env-file .env -p tidebound -f deploy/compose.mysql.yaml up -d` 启动独立 MySQL 8.4，监听 `127.0.0.1:53306`，数据保存于 `data/mysql/`。
3. `npm --prefix webfrontend run build` 构建前端。
4. `uv run python -u -m uvicorn webapp.main:app --host 127.0.0.1 --port 5201 --no-access-log --no-proxy-headers >> data/agent-debug.log 2>&1` 启动服务；不要设置多 worker。
5. 访问 `/app/` 登录；已初始化的账号不会被启动流程重置。全新数据库需要先从本机页面初始化管理员。

单元测试使用显式注入的测试存储替身，不连接开发数据库。MySQL 接入另用真实本地数据库验证账号写入、重新读取和登录。

## 管理员 Dev 工具箱与上下文重置

当前账号仅有 user/admin 两种角色；开发环境中的管理员在主界面侧边显示半透明悬浮“Dev 工具箱”，目前仅有“清空上下文”。普通账号不显示，`POST /api/chat/context/reset` 也必须由服务端验证 admin，目标固定为登录账号自身，不接受其他 UID/scope。

清空操作为当前账号创建新的有效时间线，停止并等待已有执行退出；之后的请求仅包含角色、当前输入、工具声明及按规则触发的一次性注入，不再携带旧对话。旧 Run 与 Console 请求快照保留供审计，重置不会重放工具、删除账号或修改角色与模型配置。此功能是开发调试的“从头开始”，不是任意历史轮次回退或已实现的记忆恢复。

时间线标识原子保存于 `data/agent/<scope>/state/context.json`，新 Run 保存对应标识；旧记录兼容初始时间线。会话展示、历史选取与预算展示只读取当前时间线。停止信号及提交前时间线检查阻止旧执行回写；同一账号重置等待期间拒绝新发送，旧 Run ID 不能再次提交到新时间线。重启后仍保持空历史或重置后的新对话，其他账号不受影响。

前端重置成功后撤掉流式预览、清空展示历史和草稿、恢复初始预算状态；旧订阅和未完成的发送轮询不能恢复旧消息。当前是本地单 worker dev 语义，不宣称支持跨进程协调。
