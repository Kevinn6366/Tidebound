# -*- coding: utf-8 -*-
"""
Qwen3-TTS 内置配音服务（GWC-Pro-End 第二代配音引擎）

监听 9881 端口（与 GPT-SoVITS 的 9880 并存）。基于阿里通义 Qwen3-TTS 的
「3 秒语音克隆」能力，零训练复刻音色，支持自然语言情绪指令（instruct）。

数据流（一次复刻 → 多次复用的缓存机制）：
  1. 首启 / 切角色：voices/<角色>/ref.wav + ref.txt
     → create_voice_clone_prompt() → 缓存为角色级 voice_clone_prompt
  2. 合成：text + voice_id + instruct
     → generate_voice_clone(voice_clone_prompt=缓存) → 流式返回 wav

环境要求：
  - 独立环境（由一键安装器克隆 backend/runtime 而成，免装 Python）
  - 该环境已 pip install qwen-tts（含 torch / transformers 等依赖）
  - 首次启动按需下载模型权重到 models/ 缓存

启动：
  <tts-qwen3/env>/python api.py -a 127.0.0.1 -p 9881
"""
import os
import sys
import time
import argparse
import traceback
import threading
from io import BytesIO

# 必须在 import huggingface_hub / transformers / qwen_tts 之前设置：
# 模型已本地下载完毕，强制离线加载，避免每次启动联网校验（当前网络
# 下访问 hf-mirror/官方会超时重试，导致模型加载卡住十几分钟）。
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

now_dir = os.path.dirname(os.path.abspath(__file__))
if now_dir not in sys.path:
    sys.path.insert(0, now_dir)

import numpy as np
import soundfile as sf
from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.responses import StreamingResponse, JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import shutil

parser = argparse.ArgumentParser(description="Qwen3-TTS GWC service")
parser.add_argument("-a", "--bind_addr", type=str, default="127.0.0.1", help="default: 127.0.0.1")
parser.add_argument("-p", "--port", type=int, default=9881, help="default: 9881")
parser.add_argument("--model", type=str, default="Qwen/Qwen3-TTS-12Hz-1.7B-Base",
                    help="Base 模型 ID（默认 1.7B，低显存可选 Qwen/Qwen3-TTS-12Hz-0.6B-Base）")
parser.add_argument("--cpu", action="store_true", help="强制 CPU 运行（0.6B 兜底）")
args = parser.parse_args()

HOST = args.bind_addr
PORT = args.port
MODEL_ID = args.model
FORCE_CPU = args.cpu

# 项目根（tts-qwen3/）
BASE_DIR = os.path.abspath(os.path.join(now_dir, ".."))
VOICES_DIR = os.path.join(BASE_DIR, "voices")
MODELS_DIR = os.path.join(BASE_DIR, "models")
os.makedirs(VOICES_DIR, exist_ok=True)
os.makedirs(MODELS_DIR, exist_ok=True)

APP = FastAPI(title="GWC Qwen3-TTS Service")

APP.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================================
# 情绪模板（日语场景预置，instruct 参数直接传给模型）
# ==========================================================
EMOTION_TEMPLATES = {
    "calm": {"name": "平静", "instruct": "用平静、自然的语气说话"},
    "happy": {"name": "开心", "instruct": "用开心、活泼的语气说话"},
    "sad": {"name": "悲伤", "instruct": "用悲伤、低落的语气说话"},
    "angry": {"name": "生气", "instruct": "用愤怒、强硬的语气说话"},
    "shy": {"name": "害羞", "instruct": "用害羞、小声的语气说话"},
}

# ==========================================================
# 模型与克隆 prompt 缓存
# ==========================================================
_engine = None            # qwen-tts 单例
_engine_state = {"ready": False, "loading": False, "error": "", "model": MODEL_ID,
                 "device": "cpu" if FORCE_CPU else "auto"}

# voice_id -> 克隆 prompt（首次生成后常驻内存，免去每次提特征）
_voice_prompt_cache = {}
_cache_lock = threading.Lock()


def _resolve_model_path(model_id: str):
    """在 models/ 缓存中找到该模型的本地 snapshot 绝对路径。

    模型由 ModelScope/HF 下载到 HF 缓存结构：
      models/models--<org>--<name>/snapshots/<rev>/...
    返回有权重的 snapshot 目录；找不到返回 model_id（由 HF 联网/缓存处理）。
    """
    parts = model_id.split("/")
    name = parts[-1] if len(parts) > 1 else model_id
    org = parts[0] if len(parts) > 1 else "Qwen"
    snapshots = os.path.join(MODELS_DIR, f"models--{org}--{name}", "snapshots")
    if not os.path.isdir(snapshots):
        return model_id
    # 优先选含 .safetensors 权重的 snapshot（排除旧残留的 0 字节空目录）
    best = None
    for sub in sorted(os.listdir(snapshots)):
        sp = os.path.join(snapshots, sub)
        if not os.path.isdir(sp):
            continue
        has = any(f.endswith(".safetensors") and os.path.getsize(os.path.join(r, f)) > 0
                  for r, _, files in os.walk(sp) for f in files)
        if has:
            best = sp
    return best or model_id


def _get_engine():
    """懒加载 qwen-tts 引擎，首次调用时下载/加载模型（较慢）。"""
    global _engine
    if _engine is not None:
        return _engine
    try:
        from qwen_tts import Qwen3TTSModel, Qwen3TTSTokenizer  # noqa
    except ImportError:
        _engine_state["error"] = "未安装 qwen-tts，请在设置页点「一键安装环境」后重试"
        return None

    _engine_state["loading"] = True
    try:
        import torch
        from qwen_tts import Qwen3TTSModel, Qwen3TTSTokenizer

        # 模型已本地下载完毕，用本地 snapshot 绝对路径加载，避免联网。
        # AutoProcessor.from_pretrained 不继承 cache_dir 参数，故必须传本地路径。
        model_path = _resolve_model_path(MODEL_ID)
        tok_path = _resolve_model_path("Qwen/Qwen3-TTS-Tokenizer-12Hz")

        # CPU 环境下 bfloat16 可能不支持，自动回退 float32
        use_dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32

        model = Qwen3TTSModel.from_pretrained(
            model_path,
            device_map="auto",
            torch_dtype=use_dtype,
            local_files_only=True,
            # torch 原生 SDPA 注意力（无需 flash-attn 也能加速）；若装了 flash-attn，transformers 会自动升级
            attn_implementation="sdpa",
        )
        tokenizer = Qwen3TTSTokenizer.from_pretrained(
            tok_path,
            local_files_only=True,
        )
        _engine = {"model": model, "tokenizer": tokenizer}
        _engine_state["ready"] = True
        _engine_state["loading"] = False
        _engine_state["error"] = ""
    except Exception as e:
        _engine_state["loading"] = False
        _engine_state["error"] = str(e)
        traceback.print_exc()
        _engine = None
    return _engine


def _load_engine_blocking():
    """后台线程加载模型，避免阻塞 /health 探测。"""
    if _engine_state["ready"] or _engine_state["loading"]:
        return
    threading.Thread(target=_get_engine, daemon=True).start()


# ==========================================================
# 音色扫描
# ==========================================================
def _list_voices():
    """扫描 voices/<角色>/ 目录，返回可复刻音色列表（含参考音频属性供检查是否混音）。"""
    voices = []
    if not os.path.isdir(VOICES_DIR):
        return voices
    for role in sorted(os.listdir(VOICES_DIR)):
        role_dir = os.path.join(VOICES_DIR, role)
        if not os.path.isdir(role_dir):
            continue
        ref_wav = None
        ref_txt = None
        ref_txt_content = ""
        for f in sorted(os.listdir(role_dir)):
            lower = f.lower()
            if lower == "ref.wav" or (ref_wav is None and lower.endswith((".wav", ".mp3", ".flac", ".m4a"))):
                ref_wav = os.path.join(role_dir, f)
            if lower == "ref.txt" or (ref_txt is None and lower.endswith(".txt")):
                ref_txt = os.path.join(role_dir, f)
        # 读取参考音频文字稿内容（供编辑表单回填）
        if ref_txt:
            try:
                with open(ref_txt, "r", encoding="utf-8") as f:
                    ref_txt_content = f.read().strip()
            except Exception:
                ref_txt_content = ""
        # 参考音频属性（时长/采样率/声道），帮助判断是否混音/正确
        audio_info = _probe_audio(ref_wav)
        voice = {
            "id": role,
            "name": role,
            "ref_wav": ref_wav,
            "ref_wav_name": os.path.basename(ref_wav) if ref_wav else "",
            "ref_txt": ref_txt,
            "ref_txt_content": ref_txt_content,
            "audio_info": audio_info,
            "usable": bool(ref_wav and ref_txt),
            "cached": role in _voice_prompt_cache,
        }
        voices.append(voice)
    return voices


def _probe_audio(wav_path):
    """读取音频时长/采样率/声道数，供检查参考音频是否混音/正确。"""
    if not wav_path or not os.path.isfile(wav_path):
        return {}
    try:
        import soundfile as _sf
        with _sf.SoundFile(wav_path) as f:
            return {
                "seconds": round(f.frames / f.samplerate, 2) if f.samplerate else 0,
                "sample_rate": f.samplerate,
                "channels": f.channels,
            }
    except Exception:
        return {"seconds": 0, "sample_rate": 0, "channels": 0}


def _resolve_voice(voice_id):
    for v in _list_voices():
        if v["id"] == voice_id:
            return v
    return None


def _get_or_build_prompt(voice_id):
    """获取（或首次构建并缓存）角色的克隆 prompt。"""
    with _cache_lock:
        if voice_id in _voice_prompt_cache:
            return _voice_prompt_cache[voice_id]

    voice = _resolve_voice(voice_id)
    if not voice or not voice["usable"]:
        return None

    engine = _get_engine()
    if engine is None:
        return None

    from qwen_tts import Qwen3TTSModel  # noqa
    with open(voice["ref_txt"], "r", encoding="utf-8") as f:
        prompt_text = f.read().strip()

    try:
        prompt = engine["model"].create_voice_clone_prompt(
            ref_audio=voice["ref_wav"],
            ref_text=prompt_text,
        )
    except Exception as e:
        traceback.print_exc()
        raise RuntimeError(f"克隆 [{voice_id}] 失败: {e}")

    with _cache_lock:
        _voice_prompt_cache[voice_id] = prompt
    return prompt


# ==========================================================
# 音频封装
# ==========================================================
def _pack_wav(samples: np.ndarray, sr: int) -> bytes:
    buf = BytesIO()
    sf.write(buf, samples, sr, format="wav")
    buf.seek(0)
    return buf.read()


def _wave_header(sr: int, channels=1, sample_width=2):
    import wave
    buf = BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sr)
    buf.seek(0)
    return buf.read()


# ==========================================================
# 端点
# ==========================================================
@APP.get("/health")
async def health():
    return {
        "ok": _engine_state["ready"],
        "ready": _engine_state["ready"],
        "loading": _engine_state["loading"],
        "error": _engine_state["error"],
        "model": MODEL_ID,
        "device": _engine_state["device"],
        "cached_voices": list(_voice_prompt_cache.keys()),
    }


@APP.get("/voices")
async def voices():
    return {"ok": True, "voices": _list_voices()}


def _safe_voice_id(vid: str) -> str:
    """清理音色 id，防目录穿越。"""
    import re
    vid = re.sub(r'[^\w\-.]', '_', (vid or "").strip())
    vid = vid.replace('..', '_').strip('._')
    return vid or "unnamed"


@APP.post("/voice/save")
async def voice_save(
    voice_id: str = Form(""),
    ref_text: str = Form(""),
    ref_audio: UploadFile = File(None),
    ref_audio_path: str = Form(""),
):
    """保存音色：voice_id + 参考音频（上传文件或本地路径）+ 参考音频文字稿。

    保存到 voices/<voice_id>/ref.wav + ref.txt。
    """
    vid = _safe_voice_id(voice_id)
    if not vid:
        return JSONResponse(status_code=400, content={"ok": False, "message": "voice_id 不能为空"})

    role_dir = os.path.join(VOICES_DIR, vid)
    os.makedirs(role_dir, exist_ok=True)

    # 参考音频：优先上传文件，否则用本地路径复制
    audio_saved = False
    try:
        if ref_audio is not None and getattr(ref_audio, "filename", ""):
            data = await ref_audio.read()
            if data:
                ext = os.path.splitext(ref_audio.filename or "")[1] or ".wav"
                with open(os.path.join(role_dir, "ref" + ext), "wb") as f:
                    f.write(data)
                audio_saved = True
        elif ref_audio_path and os.path.isfile(ref_audio_path):
            ext = os.path.splitext(ref_audio_path)[1] or ".wav"
            shutil.copyfile(ref_audio_path, os.path.join(role_dir, "ref" + ext))
            audio_saved = True
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "message": f"保存参考音频失败: {e}"})

    # 参考音频文字稿
    try:
        with open(os.path.join(role_dir, "ref.txt"), "w", encoding="utf-8") as f:
            f.write(ref_text.strip())
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "message": f"保存文字稿失败: {e}"})

    return {"ok": True, "voice_id": vid, "audio_saved": audio_saved,
            "voices": _list_voices()}


@APP.delete("/voice/{voice_id}")
async def voice_delete(voice_id: str):
    """删除指定音色目录。"""
    vid = _safe_voice_id(voice_id)
    role_dir = os.path.join(VOICES_DIR, vid)
    if os.path.isdir(role_dir):
        shutil.rmtree(role_dir, ignore_errors=True)
    # 清除该音色的克隆 prompt 缓存
    with _cache_lock:
        _voice_prompt_cache.pop(vid, None)
    return {"ok": True, "voice_id": vid, "voices": _list_voices()}


@APP.get("/emotions")
async def emotions():
    return {"ok": True, "emotions": [{"id": k, "name": v["name"], "instruct": v["instruct"]}
                                     for k, v in EMOTION_TEMPLATES.items()]}


@APP.get("/set_voice")
@APP.post("/set_voice")
async def set_voice(request: Request):
    """预热并缓存指定角色的克隆 prompt（可选，切角色时手动触发以加速首包）。"""
    data = {}
    if request.method == "POST":
        try:
            data = await request.json()
        except Exception:
            data = {}
    voice_id = data.get("voice_id") or request.query_params.get("voice_id", "")
    voice_id = (voice_id or "").strip()
    if not voice_id:
        return JSONResponse(status_code=400, content={"ok": False, "message": "voice_id is required"})

    engine = _get_engine()
    if engine is None:
        return JSONResponse(status_code=503,
                            content={"ok": False, "message": _engine_state["error"] or "模型未就绪（仍在加载中）"})

    try:
        _get_or_build_prompt(voice_id)
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "message": str(e)})

    return {"ok": True, "voice_id": voice_id, "cached": voice_id in _voice_prompt_cache}


@APP.post("/clone")
async def clone(request: Request):
    """立即构建并缓存指定角色的克隆 prompt（等价于 set_voice）。"""
    data = await request.json()
    voice_id = (data.get("voice_id") or "").strip()
    if not voice_id:
        return JSONResponse(status_code=400, content={"ok": False, "message": "voice_id is required"})
    engine = _get_engine()
    if engine is None:
        return JSONResponse(status_code=503,
                            content={"ok": False, "message": _engine_state["error"] or "模型未就绪（仍在加载中）"})
    try:
        _get_or_build_prompt(voice_id)
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "message": str(e)})
    return {"ok": True, "voice_id": voice_id, "cached": True}


@APP.get("/tts")
@APP.post("/tts")
async def tts(request: Request):
    """合成语音：text + voice_id + instruct → 流式/整段 wav。

    支持情绪指令 instruct（不传则用默认「平静」）。
    """
    if request.method == "POST":
        try:
            data = await request.json()
        except Exception:
            return JSONResponse(status_code=400, content={"ok": False, "message": "请求体需为 JSON"})
    else:
        data = dict(request.query_params)

    text = (data.get("text") or "").strip()
    voice_id = (data.get("voice_id") or "").strip()
    instruct = (data.get("instruct") or "").strip()
    emotion = (data.get("emotion") or "").strip()
    streaming = str(data.get("streaming", data.get("streaming_mode", "true"))).lower() in ("1", "true", "yes")
    lang = (data.get("lang") or data.get("text_lang") or "").strip()

    if not text:
        return JSONResponse(status_code=400, content={"ok": False, "message": "text is required"})
    if not voice_id:
        return JSONResponse(status_code=400, content={"ok": False, "message": "voice_id is required"})

    voice = _resolve_voice(voice_id)
    if not voice or not voice["usable"]:
        return JSONResponse(status_code=400,
                            content={"ok": False,
                                     "message": f"音色 [{voice_id}] 参考资料不完整（需 voices/{voice_id}/ref.wav + ref.txt）"})

    engine = _get_engine()
    if engine is None:
        return JSONResponse(status_code=503,
                            content={"ok": False, "message": _engine_state["error"] or "模型未就绪（仍在加载中）"})

    try:
        clone_prompt = _get_or_build_prompt(voice_id)
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "message": str(e)})

    # 情绪模板解析：显式 instruct > emotion 模板 > 默认平静
    if not instruct and emotion in EMOTION_TEMPLATES:
        instruct = EMOTION_TEMPLATES[emotion]["instruct"]

    # qwen_tts 的 language 参数要完整英文名（japanese/chinese/...），前端传的是
    # ISO 代码（ja/zh/en/ko），这里做映射，映射不到用 auto 自动检测。
    _LANG_MAP = {
        "ja": "japanese", "zh": "chinese", "zh-cn": "chinese", "en": "english", "ko": "korean",
        "japanese": "japanese", "chinese": "chinese", "english": "english", "korean": "korean",
    }
    language = _LANG_MAP.get((lang or "").lower().strip(), "auto")

    try:
        # 当前 qwen_tts 库版本：generate_voice_clone(text, language, voice_clone_prompt, ...)
        # 返回 (List[np.ndarray], sample_rate)；不提供流式/逐字 instruct 参数。
        samples_list, sr = engine["model"].generate_voice_clone(
            text=text,
            language=language,
            voice_clone_prompt=clone_prompt,
        )
        samples = samples_list[0] if isinstance(samples_list, list) else samples_list
        return Response(
            content=_pack_wav(samples, sr),
            media_type="audio/wav",
            headers={"Access-Control-Allow-Origin": "*"},
        )
    except Exception as e:
        traceback.print_exc()
        return JSONResponse(status_code=500,
                            content={"ok": False, "message": f"合成失败: {e}"},
                            headers={"Access-Control-Allow-Origin": "*"})


# 兜底：模块加载时预热模型（后台线程，不阻塞启动）
_load_engine_blocking()


if __name__ == "__main__":
    uvicorn.run(app=APP, host=HOST, port=PORT, workers=1)