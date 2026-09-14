# 账号鉴权与日志 Console

日期：2026-09-14。依据用户本轮确认，Agent 内核统一迁入 `src/tidebound/`，新增简单账号鉴权，管理员 console 当前只读取 `data/agent-debug.log`。

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

聊天、设置和资源写入 API 必须登录；普通用户不能调用管理员 API。匿名请求返回 401，角色或 UID 不匹配返回 403。旧业务能力仍不转发到 legacy 后端。

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
