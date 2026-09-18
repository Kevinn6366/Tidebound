# Qwen3-TTS 重设计方案（GWC-Pro-End 内置配音引擎）

> 目标：在 GWC-Pro-End 中引入基于 Qwen3-TTS 的新一代 TTS 引擎，并存于现有 GPT-SoVITS，实现声音复刻（日语/多语言）、低延迟、带情感。

---

## 1. 背景与现状

GWC-Pro-End 现有内置配音基于 **GPT-SoVITS**（SoVITS v2ProPlus/v4 + GPT），服务为 `tts/server/api_v2.py`（监听 9880，含 `/gwc/*` 扩展端点），后端 `backend/main.py` 负责进程管理与端点代理。

### 现状盘点

| 项目 | 现状 |
|---|---|
| 现有 TTS | GPT-SoVITS（声学模型 + 参考音频换声） |
| 现有音色 | ATRI、Sui（已训练 `.ckpt`/`.pth` 权重） |
| TTS 服务 | `tts/server/api_v2.py`，端口 9880 |
| 后端 | FastAPI（`backend/main.py`），进程管理 + 代理端点（`_tts_*`） |
| 运行时 | 共享 GPT-SoVITS 自带 Python runtime |
| 硬件 | RTX 4060 Laptop **8GB**（需与 llama.cpp LLM 争用显存） |
| 目标语言 | 日语优先（ATRI 角色），多语言可选 |

---

## 2. 需求与 Qwen3-TTS 能力对齐

| 需求 | Qwen3-TTS 能力 | 满足度 |
|---|---|---|
| 声音复刻（日语/多语言） | `1.7B-Base` 模型「3 秒语音克隆」，覆盖中日英韩等 10 种语言 | ✅ |
| 低延迟 | 双轨流式架构，**单字输入即出首包，端到端 97ms** | ✅ |
| 带情感 | 自然语言指令（`instruct` 参数）直接控制情绪/语气/语速，文本语义自适应 | ✅ |

> 对比：GPT-SoVITS 情感依赖参考音频；Qwen3-TTS 是端到端 LLM 架构，情感可**一句话指定**，是质的提升。

---

## 3. 模型选型

关键约束：8GB 显存，且需与 LLM 共存。

| 模型 | 用途 | 显存(bfloat16) | 建议 |
|---|---|---|---|
| `Qwen3-TTS-12Hz-1.7B-Base` | 语音克隆（复刻） | ~6-7GB | ✅ **核心模型** |
| `Qwen3-TTS-Tokenizer-12Hz` | 编解码（必需配套） | ~1GB | ✅ 必需 |
| `Qwen3-TTS-12Hz-0.6B-Base` | 语音克隆（轻量） | ~2-3GB | 备选（低配/CPU） |

**推荐组合**：`1.7B-Base` + `Tokenizer-12Hz`（克隆保真度最高，日语 SIM 0.81 最优，且支持流式）。

---

## 4. 框架结构

沿用现有「后端进程管理 + 独立 TTS 服务 + 代理端点」成熟架构，最小侵入、最大化复用。

```
GWC-Pro-End/
├── backend/                         # 现有 FastAPI，改动很小
│   └── main.py                      # 新增 _qwen_tts_* 进程管理端点（仿 _tts_*）
├── tts/                             # 现有 GPT-SoVITS（保留，可回退）
│   └── ...
└── tts-qwen3/                       # 【新增】Qwen3-TTS 服务目录
    ├── server/
    │   └── api.py                   # FastAPI 服务，监听 9881
    │       ├── /health
    │       ├── /voices              # 已复刻音色列表（角色 → ref 音频）
    │       ├── /clone               # 上传参考音频 → 生成并缓存克隆 prompt
    │       ├── /tts                 # text + voice_id + instruct → 流式/整段音频
    │       └── /set_voice
    ├── voices/                      # 角色参考音频
    │   └── <角色>/
    │       ├── ref.wav              # 3 秒参考音频
    │       └── ref.txt              # 参考音频文字稿（克隆质量关键）
    ├── models/                      # 权重本地缓存（按需下载）
    └── start_tts_qwen3.bat
```

### 4.1 服务层核心逻辑（`api.py`）

```
数据流（一次复刻 → 多次复用的缓存机制）：
  1. 首启/切角色：ref.wav + ref.txt
     → model.create_voice_clone_prompt()  → 缓存为角色级 voice_clone_prompt
  2. 合成：text + voice_id + instruct
     → generate_voice_clone(voice_clone_prompt=缓存) → 流式返回 PCM/wav

情感控制（instruct 参数，新增能力）：
  "用开心的语气" / "低落地" / "愤怒地" / 情绪标签
  日语场景预置情绪模板：平静 / 开心 / 悲伤 / 生气 / 害羞
```

### 4.2 后端集成（`backend/main.py`）

复用现有 `_tts_*` 模式，新增 `_qwen_tts_*`：

- `TTS_QWEN_PORT = 9881`
- `/api/tts/qwen/status` · `/start` · `/stop` · `/voices` · `/set_voice`
- 启动命令：`<runtime>\python api.py -a 127.0.0.1 -p 9881`
- 前端「声音设定」新增引擎切换：**GPT-SoVITS（旧）｜ Qwen3-TTS（新）**

---

## 5. 低延迟方案

| 手段 | 说明 | 收益 |
|---|---|---|
| 流式输出 | Base 模型支持 streaming，首包 97ms | 首字节延迟极低 |
| prompt 缓存 | `create_voice_clone_prompt` 预热常驻内存 | 省去每次提特征 |
| 模型常驻 | 服务常驻，不重复加载 | 免 10-60s 加载 |
| 分句合成 | 长文本按标点切句，边合成边放 | 表观延迟最低 |
| bfloat16 + flash-attn-2 | 官方推荐，降显存提速 | 8GB 卡可用 |

**可达目标**：首字输入 → 首包音频 < 200ms；整句延迟与语速持平。

---

## 6. 显存与共存策略（关键风险）

8GB 显卡需同时跑 LLM（llama.cpp）+ TTS，三档策略：

1. **串行互斥（推荐起步）**：LLM 生成文本与 TTS 合成本就串行，无需同时持卡，后端加显存调度锁。
2. **0.6B 降档**：需并行时 TTS 用 0.6B（~2-3GB），留出 5GB 给 LLM。
3. **CPU 回退**：0.6B 可 CPU 运行，用于边聊边合成的兜底。

---

## 7. 声音复刻/克隆工作流

```
ATRI 角色建立：
  1. 准备 3-10 秒日语参考音频（复用现有 ref_audio 或原素材截取）
  2. 准备参考音频逐字文字稿（日语，必需，影响克隆质量）
  3. POST /clone → 生成并缓存 prompt
  4. 后续任意文本 → /tts?voice_id=ATRI&instruct=开心

现有多角色（ATRI、Sui）可直接复用现有 ref_audio 素材迁移。
Qwen3-TTS 是 zero-shot 克隆，无需重新训练。
```

---

## 8. 实施阶段

| 阶段 | 内容 | 交付物 |
|---|---|---|
| P0 验证 | 装 `qwen-tts`，跑通 1.7B-Base 克隆日语，确认显存/延迟/保真 | 可行性结论 |
| P1 服务 | 写 `tts-qwen3/server/api.py`（克隆缓存 + 流式 + instruct） | 独立服务 |
| P2 集成 | 后端新增 `_qwen_tts_*` 端点 + 显存调度 | 双引擎可切 |
| P3 前端 | 声音设定加引擎切换 + 情绪模板 UI | 用户可用 |
| P4 优化 | 0.6B 档 / CPU 回退 / 流式调优 | 生产就绪 |

---

## 9. 风险与注意

- **日语克隆保真**：官方基准日语 WER 相对中文略高（约 3.8），用高质量日语参考音频 + 准确文字稿弥补。
- **显存**：1.7B bf16 约 7GB，4060 8G 上跑 TTS 时 LLM 需暂停 GPU 推理。
- **无需训练**：Qwen3-TTS 克隆是 zero-shot，比 GPT-SoVITS 省去训练环节，是最大便利点。
- **环境隔离**：官方建议独立 Python 3.12 环境，避免与现有依赖冲突。

---

## 10. 参考

- Qwen3-TTS 仓库：https://github.com/QwenLM/Qwen3-TTS
- 模型集合：https://huggingface.co/collections/Qwen/qwen3-tts
- 实时 API：https://help.aliyun.com/zh/model-studio/qwen-tts-realtime