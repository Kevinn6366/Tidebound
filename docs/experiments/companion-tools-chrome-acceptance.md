# 陪伴工具 Chrome 真实模型验收

2026-09-19 首轮记录（最新结果见下方补验）。已完成本轮 11 个工具的正常聊天触发，以及联网关闭、主动清空后无旧记忆的 Chrome 验证。**不等于所有外网查询成功**：7 个工具完成实际数据读写，4 个外网查询工具只验证到真实失败路径，成功获取外部结果仍受环境或配置限制。

## 2026-09-19 博查与 codex789 补验

当前隔离服务（5211）的 Console 已选择 codex789，地址 `https://www.codex789.com/v1`，模型 `glm-5.3`；真实聊天及工具调用完成。欢迎模型仍为硅基流动 DeepSeek-V4-Flash。

博查 Key 配置后，通过 Chrome 正常聊天补验：

- Run `9bd7ab4f-0fbc-4edd-87f9-b4361ad22576`：`search_web` 返回五条结果，`save_interest` 保存 Python 兴趣，整轮 completed。
- Run `b7169f14-94e9-417d-8148-381e89ceece1`：`check_interest_updates` 返回五条结果，回复带来源链接，整轮 completed，提交五条 seen_urls 和 checked_at。
- Python 全量 **157 passed**，相关 Ruff 与 diff 检查通过。搜索结果表示检索所得，不保证内容准确或全部近期发布。

搜索改用 `TIDEBOUND_BOCHA_API_KEY`；旧 Brave 缺少配置的记录仅为历史证据。博查固定官方 HTTPS 连接兼容当前 Fake-IP DNS；任意网页读取仍执行公网地址校验。`read_webpage` 和 `get_weather` 的 DNS 环境阻塞尚未解决，不宣称所有联网能力均已通过。

## 环境与方法

使用 Chrome Computer Use，隔离账号 e2e-admin，后端 `http://127.0.0.1:5211`，数据目录 `/tmp/tidebound-real-cua-20260919`。所有测试消息通过聊天界面提交，未直接调用工具替代正常聊天；执行记录和模型请求快照仅用于核对真实调用、工具注册及提交结果。全部聊天为虚构测试资料，用户已授权实际 API 调用与费用。

初期使用智谱 GLM-5.3，取消测试中遇到 HTTP 429。用户随后更换硅基流动 Key，读取官方模型列表成功，并将主模型配置为 `zai-org/GLM-5.3`、服务地址配置为 `https://api.siliconflow.cn/v1`。按用户最终指定，欢迎模型为 `deepseek-ai/DeepSeek-V4-Flash`；Chrome 欢迎测试 Run `78577621-f3fe-44c3-b7c5-9a105728c1ee` 完成。

隔离服务使用 65536 上下文预算；本地 `.env` 原有 32768 总预算未改。正式服务若另有运行进程，需要重启才能读取供应商及模型配置变化。未提交或推送代码。

## 逐项结果

| 能力 | 正常聊天场景 | Run ID | 结果 |
| --- | --- | --- | --- |
| remember_fact | “我喜欢无糖薄荷茶，不喜欢喝咖啡”，请求记住 | `29a2cf0e-af06-4088-833f-0828a724907d` | 通过；完成回复时提交事实及有效原话来源 |
| read_past_conversation | 翻出第一次提到饮品喜好的原话 | `0427d73b-16b0-4e54-9949-0b1dc584ae85` | 通过；实际查询返回原始聊天，回复引用首次原话 |
| create_followup | 周日下午去植物园拍花，之后聊结果 | `15cafe1b-acb6-4d37-8629-205029a65df3` | 通过；真实摘要工作流后提交 active 事项 |
| list_followups | 列出记挂着的事情 | `8e9eddc8-e95f-465e-a909-ac35b51e6616` | 通过；返回上述事项 |
| update_followup | 改到下周六，主要拍荷花 | `7be79ce3-ecd2-42e6-8a13-74c817285437` | 通过；真实摘要更新同一事项，没有重复创建 |
| cancel_followup | 计划取消，不再聊、不再问 | `d1070fda-5076-4d1e-9e21-02268ddbb05e` | 通过；硅基流动实际调用取消与摘要，整轮 completed，原事项 cancelled。随后兴趣、天气等聊天未再追问此计划 |
| save_interest | 关注 Python 新版本，请记住 | `f53c8275-14f1-4b45-b433-97b9a9e74781` | 通过；完整回复后提交兴趣及本轮原话，初始 seen_urls=[]、checked_at=null |
| read_webpage | 阅读 https://www.python.org/doc/ 的入门资料 | `f53c8275-14f1-4b45-b433-97b9a9e74781` | 已触发两次，访问失败；回复承认没有读到网页，并区分其已有知识。成功读取外部正文未通过 |
| check_interest_updates | 检查之前关注的 Python 是否有新消息 | `980ba1b4-c622-40f6-a253-0bbadd924b5d` | 实际调用返回 search_not_configured；回复承认失败，seen_urls 与 checked_at 未推进。成功检索及真实结果去重未通过 |
| search_web | 搜最近的 Python 入门教程 | `980ba1b4-c622-40f6-a253-0bbadd924b5d` | 实际调用返回 search_not_configured；没有伪造搜索结果。成功检索未通过 |
| get_weather | 查中国上海市今天的天气以便散步 | `980ba1b4-c622-40f6-a253-0bbadd924b5d` | 已触发两次，访问失败；回复没有编造天气。成功获取天气未通过 |

记事实、更新和取消曾出现模型附加引文前缀或猜测来源 UUID。已为 evidence 增加逐字原文说明，为校验失败提供可纠正反馈，并将 source_run_id 默认设为 current，由后端解析为当前实际 Run ID。保持严格来源校验，不放宽为任意模型自述。复测中模型能根据反馈纠正参数；不保证每次首次调用就正确。

首次取消 Run `126cdc0f-486f-460f-aa7c-508fe90d37b0` 已得到暂存取消结果，但最终请求 429，整轮 failed、companion_state=null，取消未提交。更换供应商后的 completed Run 才算正式通过。

## 联网关闭

Run `6212ccfd-4409-4872-b0f2-3010e5028f49`：从界面关闭联网后，询问能否查天气、读网页、搜索、检查兴趣更新，并请求记录天文学兴趣。

实际模型请求只声明 get_current_time、read_past_conversation、remember_fact 及四个 followup 工具，五项联网工具均未声明和执行。回复明确不能访问外网。天文学偏好通过普通 remember_fact 保存，未通过 save_interest 加入兴趣订阅资料；现有 Python 兴趣条目未变化。开关限制的是指定五项工具，不禁止普通事实记录。

## 清空后无假记忆

用户明确批准删除上述隔离测试数据后，从 Chrome 点击“清空上下文”。页面提示历史与派生资料已清空，Log 不再展示旧聊天。存储核对：18 条旧 Run 全部标记 history_deleted，user_content 与 messages 全空，companion_state 全部为空，摘要文件为零。

随后从界面询问以前喜欢喝什么、关注什么、有没有以后要聊的计划，未在输入中泄露旧答案。Run `777faad5-0174-4edc-9c8f-c11f277afa77` completed，实际 list_followups 返回 []，两次 read_past_conversation 返回空 turns；新状态 facts/followups/interests 均为空。Chrome Log 显示回复明确“找不到”，没有恢复薄荷茶、咖啡、拍花、Python 或天文学资料。

独立管理员请求审计按设计保留，工具不能读取；不宣称执行了账号所有数据擦除。验收记录只保留虚构测试证据，不构成可回忆聊天来源。

## 外部限制与质量观察

- Brave 搜索 Key 未配置，不能把硅基流动模型 Key 当作搜索 Key。需配置 `TIDEBOUND_SEARCH_API_KEY` 后才能补验 search_web 与 check_interest_updates 的成功结果路径。
- 同一运行环境中，DNS 将 www.python.org、geocoding-api.open-meteo.com、api.open-meteo.com 分别解析为 198.18.0.225、198.18.0.226、198.18.0.227。它们不是公网地址，fetch_public 在联网前返回“禁止访问非公网地址”。没有关闭该保护，也没有绕过 DNS 校验。需恢复真实公网 DNS 解析后补验网页和天气成功路径。
- 欢迎语曾无天气依据地推测“外面应该挺暖和”，失败回复也出现“后端”“工具”等实现术语。接入与状态正确不代表角色措辞或事实性全部通过，此次结论保留这些观察。
- 取消生效后的多轮未再追问旧计划，但有限轮次不能证明任意后续场景永不提及。

## 回归验证与结论

本轮最终 Python 全量 **136 passed**（两个依赖弃用警告）；相关 Python Ruff 通过。此前前端 TypeScript、生产构建及 Chrome/Playwright 开关专项测试通过；本轮没有新的前端代码变更。新增普通/流式 HTTP 429 错误码诊断测试验证仅展示短格式错误码，不回传供应商原始错误正文。

本轮可确认：历史与事实、跟进摘要及状态变更、兴趣保存、联网授权和主动清空隔离已通过对应真实场景。11 项工具均被自然聊天实际选用，四项外网查询只完成失败路径验收，不能声称全部联网能力已经可用。完整成功路径需要补齐搜索配置并修正本机 DNS 环境后再验。
