# 未启用的上游前端参考

`frontend/` 原位于 `gwcpro/frontend/`，`web_static/` 原位于 `gwcpro/backend/web_static/`。为保留后续迁移依据，本次移动完整源码与资源；当前新应用不导入这里的 AppCore、登录、存档、插件、模型或工具调用。

这些代码尚未按新架构全面改造，不应作为 Tidebound 的运行入口。其旧启动脚本、依赖锁与配置只用于追溯，不代表当前启动方式。原完整界面已恢复到 `webfrontend/src/gwc/`，并从中移除了旧模型执行；新增通信适配在 `webfrontend/src/services/`，请使用仓库根目录 README 的启动命令。
