# Tidebound Web 前端

当前入口恢复 GWC-Pro 的完整原界面：对话输入、附件、快捷栏、存读档、所有设置页签，以及立绘和剧本编辑器。原实现位于 `src/gwc/`，新增 TypeScript 通信在 `src/services/`。

对话发送经根目录 `backend/chat.py` 委托 `src/tidebound/runtime/` 执行，首版仅支持文本和时间工具，拒绝附件时保留草稿。模型执行、上下文、记忆和剧本生成逻辑不在前端继续运行。原有设置和资源可编辑保存；依赖尚未迁移服务的操作明确返回未接入。

在本目录执行 `npm ci`；开发使用 `npm run dev`，构建使用 `npm run build`。开发前先在仓库根目录启动 `uv run uvicorn webapp.main:app --host 127.0.0.1 --port 5201`。

检查：`npm run lint`、`npm run build`。浏览器测试：`npx playwright install chromium`、`npm run test:e2e`，测试前释放 5201 和 5173 端口。

`legacy/` 保留原始参考，不参与运行；`public/vendor/` 保留上游第三方库及许可。原 JSX 不做无关重写，新 TypeScript 使用严格类型检查。


登录入口为 `/app/`，登录后进入 `/app/{uid}`。管理员可进入 `/app/{uid}/console` 查看 `data/agent-debug.log` 末尾 100 行。账号与 MySQL 启动方式见 [账号与 Console 规格](../docs/specs/accounts-and-console.md)。浏览器测试使用 5211、5212、5174 端口；本机已安装 Chrome 时可使用 `PLAYWRIGHT_CHROMIUM_CHANNEL=chrome npm run test:e2e`。
