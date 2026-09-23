<div align="center">

# 汐伴 · Tidebound

**让每一次对话，都成为下一次相见的起点。**

面向长期陪伴的角色 Agent · Galgame 风格 Web 界面 · 可追溯的工具与工作流

[快速开始](#快速开始) · [当前能力](#当前能力) · [架构](#架构) · [Future](#future) · [开发文档](#开发文档)

</div>

---

Tidebound 是一个以持续关系为核心的角色陪伴项目。角色有自己的性格、世界背景和表达方式，也能回看对话、保存用户确认的事实、跟进正在讨论的事情，并在允许联网时了解现实世界。

我们希望把日常闲聊里的温度，和 Agent 执行时的可靠性放在一起：她可以得意、嘴硬、偶尔胡说八道；保存了什么、调用了什么、事情有没有完成，则应该能够被检查。

**当前版本：v0.04 · 开发阶段 · 当前支持角色：亚托莉（ATRI）。**

## 与亚托莉相见

目前提供亚托莉的角色与世界观提示词，围绕她的好奇、直率和“高性能”的小得意，持续打磨日常聊天体验。角色设定、表达规则与工具规则分层管理，性格通过具体的反应表现出来。

你可以从一句“今天好累”开始，聊一只路边的猫、一顿没做好的晚饭，或让她了解你刚提到的新鲜事。对话可以轻松，也可以认真，留一点接话的空隙，也留一点下一次继续的余地。

前端支持立绘、Live2D 资源和背景等展示配置；所需角色资源由使用者自行准备。当前 Agent 入口固定为亚托莉，更多角色的标准化接入属于后续方向。

## 当前能力

| 能力 | 当前支持 |
| --- | --- |
| **连续对话** | 文本流式回复、停止生成、历史记录、登录欢迎语；欢迎模型可单独配置 |
| **上下文管理** | 请求预算检查、后台滚动摘要、管理员主动压缩与预算调整；压缩保留历史原文 |
| **回忆与事实** | 按关键词或轮次回看有效历史，保存带用户原话依据的事实 |
| **事项跟进** | 创建、查看、更新和取消跟进事项；工作流整理摘要，再随本轮成功完成提交状态 |
| **联网能力** | 博查搜索、文本网页读取、天气查询、兴趣保存与按需检查更新 |
| **搜索表达** | 先流式接话，再经过语境概括、检索与阅读印象等处理，输出后续回复 |
| **账号隔离** | MySQL 账号与登录会话；按账号隔离聊天历史、摘要和陪伴状态 |
| **管理员 Console** | 查看实际模型请求、运行日志、工具与工作流阶段；切换已配置的主聊天渠道 |
| **角色界面** | Galgame 风格对话框、背景、立绘与 Live2D 展示、设置和资源管理 |






## 快速开始

### Linux 服务器 ZIP 部署

将发布 ZIP 解压到服务器，安装 Docker Engine、Compose 插件和 curl，开放所选的 HTTP 端口，然后在解压目录运行：

```bash
chmod +x deploy.sh
./deploy.sh
```

首次运行会生成 `.env` 并提示填写两个 MySQL 密码。填好后再次运行 `./deploy.sh`，脚本生成首次管理员初始化口令、构建前端与后端镜像、启动 MySQL 和 WebApp、验证 HTTP 健康接口与页面，并输出访问地址和口令。默认地址为 `http://服务器IP:8080/app/`；可在 `.env` 设置 `TIDEBOUND_PUBLIC_PORT`，或运行前设置 `TIDEBOUND_PUBLIC_HOST` 用于打印指定域名。首次访问页面需要填写该口令并创建管理员账号，再在「设置 → 模型接口」中为该账号保存硅基流动 API Key。每个账号独立配置；生产环境不会把全局 `.env` 模型密钥自动提供给未配置的账号。数据库和运行数据保存在 Docker 命名卷中，重复运行脚本不会清空。

ZIP 不包含 `.env`、本地数据或模型凭据。公网正式使用应在服务器前配置 HTTPS 反向代理与防火墙，只开放需要的端口；直接 HTTP 地址用于初次连通验证。

以下是当前单机、单 worker 的开发运行方式。需要 **Python 3.11+、uv、Node.js 22.12+、npm，以及 Docker Compose**（用于启动 MySQL；也可使用已有 MySQL）。

### 1. 获取项目并安装依赖

```bash
git clone https://github.com/Kevinn6366/Tidebound.git
cd Tidebound
uv sync
npm --prefix webfrontend ci
cp .env.example .env
```

### 2. 配置服务

编辑 `.env`，填写模型凭据与数据库密码。下面展示硅基流动的配置组合；请将占位值替换为自己的密钥：

```dotenv
TIDEBOUND_MODE=dev
TIDEBOUND_LLM_BASE_URL=https://api.siliconflow.cn/v1
TIDEBOUND_LLM_MODEL=zai-org/GLM-5.3
TIDEBOUND_LLM_API_KEY=填写你的硅基流动密钥

TIDEBOUND_MEET_MODEL=deepseek-ai/DeepSeek-V4-Flash
TIDEBOUND_WEBSEARCH_MODEL=deepseek-ai/DeepSeek-V4-Flash

TIDEBOUND_MYSQL_PASSWORD=设置数据库用户密码
TIDEBOUND_MYSQL_ROOT_PASSWORD=设置数据库管理员密码

# 可选：开启搜索和兴趣更新时使用
TIDEBOUND_BOCHA_API_KEY=填写你的博查密钥
```

欢迎与搜索工作流的地址、密钥留空时，复用原始 `TIDEBOUND_LLM_*` 配置。若要使用独立渠道，可分别设置 `TIDEBOUND_MEET_BASE_URL/API_KEY` 和 `TIDEBOUND_WEBSEARCH_BASE_URL/API_KEY`。

配置项全集见 [`.env.example`](.env.example)。切换供应商时，需要一起核对地址、模型 ID 和推理参数，不能只替换密钥。搜索密钥在[博查开放平台](https://open.bocha.cn/)配置，与模型密钥独立；没有搜索密钥也可以进行普通聊天。

管理员 Console 支持切换原始模型渠道与 codex789 中转渠道，后者通过 `TIDEBOUND_RELAY_*` 配置。切换影响服务内各账号的下一轮主聊天，不改变正在运行的请求，也不自动切换独立的欢迎和搜索工作流。

### 3. 启动数据库、构建前端

```bash
docker compose --env-file .env -p tidebound -f deploy/compose.mysql.yaml up -d
npm --prefix webfrontend run build
mkdir -p data
```

默认 MySQL 监听 `127.0.0.1:53306`，数据保存在 `data/mysql/`。首次启动需等待数据库就绪。

### 4. 启动 Tidebound

```bash
uv run python -u -m uvicorn webapp.main:app \
  --host 127.0.0.1 --port 5201 \
  --no-access-log --no-proxy-headers \
  >> data/agent-debug.log 2>&1
```

打开 **[http://127.0.0.1:5201/app/](http://127.0.0.1:5201/app/)**，首次运行从本机页面初始化管理员，随后登录并开始聊天。前端构建产物由 FastAPI 提供；服务日志写入 `data/agent-debug.log`。

修改前端时，可保持后端运行，在另一终端执行：

```bash
npm --prefix webfrontend run dev
```

Vite 开发入口为 `http://127.0.0.1:5173/app/`，API 代理到 `5201`。模型凭据与运行数据留在服务端，不进入前端构建或版本控制。当前不要启用多个 Uvicorn worker；完整生产部署还在后续规划中。

### 启动脚本（Windows / Linux / macOS）

首次使用先安装上述开发工具，将 `.env.example` 复制为 `.env` 并填写配置，再启动 Docker Desktop / Docker Engine。之后可在根目录使用脚本代替手动启动：

```powershell
# Windows（PowerShell；也可直接双击 start.bat）
.\start.bat
```

```bash
# Linux / macOS
./start.sh
```

脚本安装锁定依赖、等待 MySQL 就绪，并启动后端和 Vite 前端；访问 [http://127.0.0.1:5173/app/](http://127.0.0.1:5173/app/)。已有 MySQL 时使用 `start.bat --skip-db` 或 `./start.sh --skip-db`，连接参数仍读取 `.env`。启动前需释放 `5201` 和 `5173` 端口。

Linux/macOS 在当前终端按 `Ctrl+C` 停止前后端；Windows 在两个服务窗口分别按 `Ctrl+C`。数据库容器保持运行，后端日志写入 `data/agent-debug.log`。脚本使用 Vite 开发页面；需要通过后端 `5201/app/` 访问时，仍需按上文构建前端。

## 架构

Tidebound 采用 Python 与 React 组成的模块化单体。Agent 执行循环由项目直接实现，业务内核与界面、HTTP 协议分别组织。

```text
React / Galgame Web UI
          │
          ▼
FastAPI · 认证、通信、输入校验、展示适配
          │
          ▼
Agent Runtime · 会话协调、执行、停止与提交
          │
          ├── Context       预算、历史选取与摘要
          ├── Prompts       角色、世界观与按需规则
          ├── Tools         有边界的行动与状态读写
          ├── Workflows     欢迎、压缩、搜索与跟进
          └── Storage       账号、历史、状态与审计
```

**Agent 决定怎样回应和使用能力；工作流完成预定义过程；Runtime 决定执行是否有效。** 工作流中的模型调用不被当作另一个具有自主权限的 Agent。

账号使用 MySQL；当前对话执行记录、摘要、陪伴状态和请求审计使用本地持久化。原始历史、模型本次可见的上下文，以及摘要和事实各有职责，避免把“全塞进上下文”当成长期记忆。

下面按当前目录展开主要职责，省略缓存、构建产物和部分辅助文件：

```text
Tidebound/
├── webfrontend/                        # Web 展示与交互
│   ├── src/
│   │   ├── gwc/                        # 基于上游保留的 Galgame 界面与设置
│   │   ├── components/                 # 登录、Console、开发工具箱与预算展示
│   │   ├── hooks/                      # 聊天状态与流式文本呈现
│   │   ├── services/                   # 聊天、认证、日志与模型渠道 API 客户端
│   │   └── App.tsx                     # 页面入口与路由组织
│   ├── public/                         # 静态资源与第三方前端库
│   ├── tests/                          # Playwright 浏览器 E2E
│   └── legacy/                         # 原始前端参考，不参与构建
│
├── webapp/                             # FastAPI 通信与展示适配
│   ├── main.py                         # 应用组装、生命周期与路由注册
│   ├── auth/                           # 认证、登录会话、身份与权限校验
│   ├── chat.py / chat_service.py       # 聊天接口、流式传输与运行时调用适配
│   ├── console.py / console_log.py     # 管理接口、模型请求与日志读取
│   ├── ui_routes.py / ui_store.py      # 设置、存档等界面数据的通信与存储
│   ├── assets.py                       # 角色展示资源管理
│   └── schemas.py                      # 通信数据结构与输入校验
│
├── src/tidebound/                      # Agent 业务内核
│   ├── runtime/                        # 会话协调与有限执行生命周期
│   │   ├── session.py                  # 会话入口、并发控制与状态协调
│   │   ├── agent_loop.py               # 模型调用、工具执行与回复循环
│   │   ├── compaction.py               # 后台压缩调度与主执行衔接
│   │   ├── companion.py                # 陪伴资料恢复与上下文注入
│   │   ├── model_channels.py           # 主聊天模型渠道选择
│   │   └── events.py / preview.py      # 运行事件与流式预览通道
│   ├── context/                        # 请求预算与压缩材料规划
│   ├── tools/
│   │   ├── registry.py                 # 能力注册、声明与调用校验
│   │   ├── companion/                  # 历史回看、事实与跟进事项操作
│   │   ├── internet/                   # 搜索、网页、天气与兴趣更新访问
│   │   └── getcurrenttime/             # 当前时间查询
│   ├── workflows/
│   │   ├── meet/                       # 生成并校验登录欢迎语
│   │   ├── compaction/                 # 读取历史、规划、生成、校验与提交摘要
│   │   ├── followup/                   # 跟进事项的摘要整理
│   │   └── websearch/                  # 首反应、语境概括、检索与阅读印象
│   ├── storage/                        # 账号、Run、摘要、陪伴状态和请求审计
│   ├── memory/                         # 预留：独立长期记忆模块
│   ├── sandbox/                        # 预留：执行隔离，目前未开放代码执行
│   ├── prompting.py                    # 提示词 bundle 加载、组合与校验
│   ├── llm.py / llm_stream.py          # 模型请求与流式响应解析
│   └── config.py                       # 模型与运行时配置
│
├── prompts/                            # 提示词唯一内容来源
│   ├── master.yaml                     # purpose 与提示词文件的映射
│   ├── master/
│   │   ├── chat.character/             # 亚托莉的身份、性格与表达
│   │   ├── chat.safety/                # 对话边界与内部信息表达规则
│   │   ├── world.worldview/            # 角色来历与世界背景
│   │   ├── chat.meet/                  # 登录欢迎语规则
│   │   ├── companion.rules/            # 陪伴资料与跟进能力的使用规则
│   │   ├── context.compaction/         # 历史摘要生成规则
│   │   ├── context.injection/          # 摘要作为上下文资料的使用规则
│   │   ├── tools.injection/            # 工具调用后的专项规则
│   │   ├── tools.websearch/            # 搜索各节点及续答规则
│   │   └── workflow.followup/          # 跟进摘要规则
│   └── RAW/                            # 原作台词资料，不是当前用户历史
│
├── docs/
│   ├── specs/                          # 当前有效的架构与专项规格
│   ├── architecture/discussions/       # 设计讨论与对话评估记录
│   ├── experiments/                    # 实验与验收记录
│   ├── releases/                      # 版本记录
│   └── future.md                       # 后续方向
├── tests/
│   ├── runtime/                        # 执行、工具、工作流与存储行为测试
│   ├── webapp/                         # 通信、认证与管理员接口测试
│   └── support/                        # 测试账号存储、模型替身与 E2E 服务
├── scripts/                            # 提示词检查与上下文实验脚本
├── shell/                              # Shell 检查入口
├── deploy/                             # MySQL 开发部署配置
├── character_analysis/                 # 角色研究资料
├── legacy/gwcpro/                      # 上游业务参考，不导入旧 Agent
├── data/                               # 本地运行数据与资源，不进入版本控制
├── .env.example                        # 配置模板，不含真实凭据
├── pyproject.toml / uv.lock             # Python 依赖与锁定版本
├── VERSION                             # 产品版本号
└── AGENTS.md                           # 仓库开发规范
```

`memory/` 与 `sandbox/` 目前仅为职责预留。已有事实与摘要能力分别落在 `storage/`、`context/`、`tools/` 和 `workflows/`，目录存在不代表完整长期记忆或代码执行已经实现。


## Future

下面汇总当前规格与讨论中的后续方向。**已经可用的能力见上文；这里的项目尚未完整实现，不代表固定排期。**

### 持续关系与记忆

- [ ] 更完整的长期记忆检索与纠错：按需寻找相关经历，支持事实更正与来源追溯。
- [ ] 更精细的上下文材料预算、选取和场景提示词注入；在已实现的固定世界观与滚动摘要上继续演进。
- [ ] 管理员历史回退及相关状态恢复，保持摘要、记忆和派生事项与有效时间线一致。
- [ ] 一次 Run 接收多条用户补充消息，完善执行中输入与停止的归属规则。

### 更丰富的相处方式

- [ ] 语音输入、TTS、口型与角色动作，让文字之外的表达真正接入运行时。
- [ ] 更多角色的标准化接入，复用同一套业务内核。
- [ ] 独立 App 形态，通过相同服务端能力延续关系与历史。

以下来自陪伴能力的讨论候选池，范围与优先级仍待确定：

- [ ] **共同活动**：一起专注、读书、练口语或写故事，保存进度，支持暂停和继续。
- [ ] **共同收藏与创作**：纪念时刻、小日记、愿望清单、故事与其他可继续编辑的作品；图片、明信片和纪念图属于更后续候选。
- [ ] **可调整的陪伴方式**：主动联系时段、频率、暂缓跟进，以及倾诉时先听等明确偏好的持久化控制。
- [ ] **主动联系与可靠提醒**：定时兴趣检查、合适时机分享更新、明确提醒的调度与送达，区分自然关心和到点执行的承诺。

### Agent 与工程能力

- [ ] Python 代码生成工作流；生成结果是否执行、如何授权和隔离仍待确定。
- [ ] 多 Agent 协作，明确分工、权限和结果归属。
- [ ] 完善工作流触发、跨轮任务恢复及外部副作用处理。
- [ ] Linux / Docker 生产部署方案，以及与之配套的并发、运维和数据生命周期设计。
- [ ] 发布由开发者维护的 Web 在线体验端，让大家无需本地部署，也能与亚托莉相见；体验地址与开放时间将在后续公布。

当前不建设独立世界模拟器、分布式基础设施或通用插件平台，也不将规划中的代码执行能力作为默认工具开放。

路线依据：[Future 文档](docs/future.md)、[宏观架构](docs/specs/architecture.md)、[上下文与场景设计](docs/specs/context-budget-and-scene-injection.md)、[陪伴能力讨论 #12](https://github.com/Kevinn6366/Tidebound/issues/12)。讨论中的能力若进入迭代，会先明确专项规格和验收范围。

## 开发与验证

```bash
# 后端与运行时
uv run pytest
uv run ruff check .

# 前端
npm --prefix webfrontend run lint
npm --prefix webfrontend run build

# 浏览器 E2E（首次需要安装浏览器）
cd webfrontend
npx playwright install chromium
npm run test:e2e
```

浏览器测试使用独立测试服务与账号，运行前请释放 `5211`、`5212` 和 `5174` 端口。使用本机 Chrome 的方式见[前端开发说明](webfrontend/README.md)。

程序行为通过受控测试验证；性格、接话节奏与长期相处体验通过真实模型对话持续评估。页面仍保留部分上游设置与功能入口，**入口存在不表示对应后端已接入**；TTS、语音等能力的实际状态以专项规格为准。

欢迎通过 [Issues](https://github.com/Kevinn6366/Tidebound/issues) 提交问题、讨论设计或分享对话体验，也欢迎提交 [Pull Request](https://github.com/Kevinn6366/Tidebound/pulls)，一起完善代码、文档与角色体验。

贡献前请阅读 [AGENTS.md](AGENTS.md) 和相关规格；提交 PR 时，请说明改动目的、影响范围与验证结果。较大的功能或架构调整，建议先通过 Issue 讨论。

## 开发文档

| 文档 | 内容 |
| --- | --- |
| [宏观架构](docs/specs/architecture.md) | 产品范围、模块职责与演进原则 |
| [Agent 执行循环](docs/specs/agent-loop-v0.01.md) | 当前运行时基础 |
| [提示词分层](docs/specs/prompt-injection.md) | 角色、世界观与临时规则的注入 |
| [上下文压缩](docs/specs/context-compaction.md) | 摘要、预算和有效历史 |
| [陪伴工具](docs/specs/companion-tools.md) | 回忆、跟进、联网与兴趣工作流 |
| [流式聊天](docs/specs/chat-streaming.md) | 回复传输与停止 |
| [账号与 Console](docs/specs/accounts-and-console.md) | 登录、权限、模型配置与审计 |
| [前端迁移](docs/specs/web-migration.md) | 已接入能力与保留界面的边界 |

## 致谢

Web 界面基于 [GWC-Pro](https://github.com/QiuSui1145/GWC-Pro) 演进，感谢上游作者的工作。Tidebound 的 Agent 业务内核在此基础上独立实现。

亚托莉来自 [ATRI -My Dear Moments-](https://atri-mdm.com/)。本项目为非官方项目；角色、作品及第三方资源的权利归各自权利人所有，相关素材与依赖遵循其各自许可。

---

<div align="center">

潮水会涨落，聊天可以慢慢来。<br>
下一次见面，也从一句「在吗」开始。

</div>
