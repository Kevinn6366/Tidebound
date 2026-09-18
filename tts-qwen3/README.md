# 内置配音 (Qwen3-TTS)

供 GWC 的「内置配音」功能使用的**第二代配音引擎**，基于阿里通义 Qwen3-TTS，
与现有 GPT-SoVITS 并存，支持引擎开关无缝切换。

## 与 GPT-SoVITS 的对比

| | GPT-SoVITS（旧） | Qwen3-TTS（新） |
|---|---|---|
| 端口 | 9880 | 9881 |
| 复刻方式 | 需训练 `.ckpt`/`.pth` | **zero-shot 克隆**（3 秒参考音频） |
| 情感控制 | 依赖参考音频 | **一句话 instruct 指定** |
| 延迟 | 首包较慢 | 流式，端到端 97ms |
| 环境 | 共享 GPT-SoVITS runtime | 克隆自带 runtime（免装 Python） |

## 目录结构

```
tts-qwen3/
  server/
    api.py                   Qwen3-TTS FastAPI 服务（端口 9881）
  voices/                    角色参考音频
    <角色>/
      ref.wav                3~10 秒参考音频
      ref.txt                参考音频逐字文字稿（克隆质量关键）
  models/                    模型权重本地缓存（按需下载）
  requirements.txt           独立环境依赖
  env/                       独立环境（由一键安装器克隆自 backend/runtime，见下）
  start_tts_qwen3.bat        手动启动（也可在设置里一键启动）
```

## 安装（一次性，免装 Python）

Qwen3-TTS 使用**独立环境**，与 GPT-SoVITS 依赖隔离。分发的机器上**无需额外安装 Python**：

> **推荐**：GWC 设置 → 声音设定 → 引擎切「Qwen3-TTS」→ 点「一键安装环境」。

一键安装器会：
1. 把项目自带 `backend/runtime`（内置 python.exe + pip）复制成 `tts-qwen3/env`；
2. 用该 python 直接 `pip install` 装 qwen-tts 及依赖。

> 为什么不用 venv：项目自带 runtime 是 Python embeddable 发行版（体积小），
> 官方裁剪了 `venv`/`ensurepip` 模块，无法用它创建虚拟环境；克隆 runtime 则完全绕开此限制。

也可手动：设置环境变量 `GWC_QWEN_TTS_RUNTIME` 指向任意已装好 `qwen-tts` 的 python.exe。

## 使用

**推荐**：GWC 设置 → 声音设定 → 引擎切换选「Qwen3-TTS」→ 点「启动」，
随后选择已复刻音色与情绪模板。

**手动**：双击 `start_tts_qwen3.bat`，服务监听 `127.0.0.1:9881`。

首次启动会按需下载模型权重（1.7B 约 6-7GB / 0.6B 约 2-3GB）到 `models/`，请预留磁盘与显存空间。

## 显存策略（8GB 卡，需与 llama.cpp LLM 共存）

1. **串行互斥（推荐起步）**：LLM 生成文本与 TTS 合成本就串行，无需同时持卡。
2. **0.6B 降档**：需并行时改用 0.6B（~2-3GB），设置 `GWC_QWEN_TTS_MODEL=Qwen3-TTS-12Hz-0.6B-Base`。
3. **CPU 回退**：0.6B 可 CPU 运行（加 `--cpu` 启动），边聊边合成兜底。

## 添加音色

参考 [voices/README.md](voices/README.md)：每个角色一个子目录，放 `ref.wav` + `ref.txt`。

现有多角色（ATRI、Sui）可直接复用 `tts/ref_audio/` 素材迁移。

## 情绪控制

预置 5 种日语情绪模板（`/emotions` 端点）：平静 / 开心 / 悲伤 / 生气 / 害羞。
instruct 参数为自然语言，也可自由输入（如「温柔地、带一点撒娇的感觉」）。

## 参考

- Qwen3-TTS 仓库：https://github.com/QwenLM/Qwen3-TTS
- 模型集合：https://huggingface.co/collections/Qwen/qwen3-tts