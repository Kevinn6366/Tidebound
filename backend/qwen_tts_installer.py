# -*- coding: utf-8 -*-
"""
Qwen3-TTS 一键安装器（免装 Python / 免 venv 方案）

背景：项目自带的 backend/runtime/python.exe 是 Python embeddable 发行版，
被裁剪了 venv/ensurepip 模块，无法用它创建虚拟环境；但用户分发的机器上
通常也没有可用的完整 Python。为了让「分发后一键可用、无需额外安装 Python」，
本安装器采用「克隆 runtime」方案代替 venv：

  1. 把 backend/runtime 整个目录复制成 tts-qwen3/env（自带 python.exe + pip）
  2. 用该克隆的 python 直接 pip install qwen-tts 及服务依赖
  3. （可选）预下载模型权重到 tts-qwen3/models

这样 Qwen3-TTS 拥有完全独立的 site-packages，既不污染 backend，
也不依赖任何系统 Python / venv 模块。

网络问题应对：
  - pip 默认走清华镜像（可配置 GWC_PIP_INDEX）
  - 模型下载默认走 HuggingFace 官方（可配置 GWC_HF_ENDPOINT，
    中国大陆可设 https://hf-mirror.com）
"""
import os
import sys
import shutil
import subprocess
import threading
import time

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
BACKEND_DIR = os.path.join(BASE_DIR, "backend")
SOURCE_RUNTIME = os.path.join(BACKEND_DIR, "runtime")     # 源：项目自带 runtime
QWEN_TTS_DIR = os.path.join(BASE_DIR, "tts-qwen3")
ENV_DIR = os.path.join(QWEN_TTS_DIR, "env")               # 目标：克隆的独立环境
SERVER_DIR = os.path.join(QWEN_TTS_DIR, "server")
MODELS_DIR = os.path.join(QWEN_TTS_DIR, "models")

# 国内镜像（网络问题应对）
DEFAULT_PIP_INDEX = "https://pypi.tuna.tsinghua.edu.cn/simple"
# HuggingFace 国内镜像端点
DEFAULT_HF_ENDPOINT = "https://hf-mirror.com"

DEFAULT_MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
TOKENIZER_MODEL = "Qwen/Qwen3-TTS-Tokenizer-12Hz"

# Qwen3-TTS 可选 Base 模型型号（供「模型管理」切换/下载/卸载）
# tokenizer 是固定配套（Qwen3-TTS-Tokenizer-12Hz），不在此列表。
QWEN3_TTS_MODELS = [
    {
        "id": "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
        "label": "1.7B-Base（推荐）",
        "size_desc": "约 4.5GB",
        "vram_desc": "需约 7GB 显存",
        "note": "克隆保真度最高，日语 SIM 最优，支持流式",
    },
    {
        "id": "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
        "label": "0.6B-Base（轻量）",
        "size_desc": "约 2GB",
        "vram_desc": "需约 3GB 显存",
        "note": "低显存 / CPU 兜底，保真度略低",
    },
]

# torch CUDA 下载镜像列表（供「torch 镜像选择」）
TORCH_MIRRORS = [
    {"id": "sjtug", "label": "上海交大 SJTUG（推荐，国内快）",
     "base": "https://mirrors.sjtug.sjtu.edu.cn/pytorch-wheels"},
    {"id": "official", "label": "PyTorch 官方（download.pytorch.org）",
     "base": "https://download.pytorch.org/whl"},
    {"id": "aliyun", "label": "阿里云（mirrors.aliyun.com，可能不可用）",
     "base": "https://mirrors.aliyun.com/pytorch-wheels"},
]

DEPS = ["qwen-tts", "fastapi", "uvicorn", "soundfile", "numpy"]


def _py_exe():
    """独立克隆环境内的 python.exe 路径（embeddable 的 python.exe 在根目录，不在 Scripts 下）。"""
    return os.path.join(ENV_DIR, "python.exe")


# 进程内缓存：环境探测（is_installed / is_model_ready / get_torch_info）会走
# subprocess 或文件遍历，前端反复刷新时每次都探测会导致「环境检测时间过长」。
# 这里做 60 秒 TTL 缓存，命中直接返回上次结果。
_ENV_CACHE = {}
_ENV_CACHE_TTL = 60


def _cached(key, fn):
    now = time.time()
    hit = _ENV_CACHE.get(key)
    if hit and (now - hit["ts"]) < _ENV_CACHE_TTL:
        return hit["val"]
    val = fn()
    _ENV_CACHE[key] = {"ts": now, "val": val}
    return val


def is_installed():
    """判断独立环境是否已就绪（python.exe 存在 + qwen-tts 已装）。带缓存。"""
    def _probe():
        py = _py_exe()
        if not os.path.isfile(py):
            return False
        try:
            r = subprocess.run(
                [py, "-c", "import qwen_tts"],
                capture_output=True, timeout=15,
            )
            return r.returncode == 0
        except Exception:
            return False
    return _cached("is_installed", _probe)


class QwenInstallProgress:
    """安装进度（供前端轮询）。"""

    def __init__(self):
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        with self.lock:
            self.running = False
            self.done = False
            self.ok = False
            self.step = ""
            self.percent = 0
            self.error = ""
            self.log = []
            self.started_at = 0

    def set(self, **kw):
        with self.lock:
            for k, v in kw.items():
                setattr(self, k, v)

    def append_log(self, line):
        with self.lock:
            self.log.append(line)
            if len(self.log) > 200:
                self.log = self.log[-200:]

    def snapshot(self):
        with self.lock:
            return {
                "running": self.running, "done": self.done, "ok": self.ok,
                "step": self.step, "percent": self.percent, "error": self.error,
                "log": list(self.log[-30:]),
                "installed": is_installed(),
                "elapsed": int(time.time() - self.started_at) if self.started_at else 0,
            }


PROGRESS = QwenInstallProgress()
# 模型下载独立进度（避免与「一键安装」的 PROGRESS 互相覆盖）
MODEL_PROGRESS = QwenInstallProgress()


# ============================================================
# 进程跟踪 / 取消机制：所有下载/加载进程都可被「停止」按钮强制终止
# ============================================================
_ACTIVE_PROC = None            # 当前正在运行的子进程（Popen 对象）
_ACTIVE_LOCK = threading.Lock()
_CANCEL_EVENT = threading.Event()  # 取消标志


def _set_active(proc):
    global _ACTIVE_PROC
    with _ACTIVE_LOCK:
        _ACTIVE_PROC = proc


def _clear_active():
    global _ACTIVE_PROC
    with _ACTIVE_LOCK:
        _ACTIVE_PROC = None


def cancel_active_task():
    """强制终止当前正在运行的下载/安装子进程（供「停止」按钮调用）。"""
    global _ACTIVE_PROC
    _CANCEL_EVENT.set()
    with _ACTIVE_LOCK:
        proc = _ACTIVE_PROC
    if proc and proc.poll() is None:
        try:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                               capture_output=True, timeout=15)
            else:
                proc.terminate()
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    try:
        _ACTIVE_PROC = None
    except Exception:
        pass


def _run(cmd, progress, cwd=None, timeout=None, env=None, no_progress_bar=True):
    """运行子进程，把 stdout/stderr 流式汇入进度日志。

    用独立 reader 线程读 stdout 到队列（Windows 上 select 不支持 pipe 会抛
    WinError 10093，故不能用 select），主线程带超时从队列取，超时则周期性
    更新「下载中耗时」提示。按 \\r/\\n 拆分（\\r 为进度条帧，只更新 step 不写日志）。
    """
    global _CANCEL_EVENT
    _CANCEL_EVENT.clear()
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    progress.append_log("$ " + " ".join(cmd))
    try:
        p = subprocess.Popen(
            cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            env=full_env, text=False, encoding=None,
        )
    except Exception as e:
        progress.append_log(f"> 启动失败: {e}")
        return 1
    _set_active(p)

    import queue as _queue
    import threading as _threading
    q = _queue.Queue()

    def reader():
        try:
            while True:
                chunk = p.stdout.read(4096)
                if not chunk:
                    break
                q.put(chunk)
        except Exception:
            pass
        finally:
            q.put(None)  # 结束标记

    _threading.Thread(target=reader, daemon=True).start()

    buf = b""
    start_time = time.time()
    last_report = 0

    def _drain_buf():
        nonlocal buf
        while True:
            idx_n = buf.find(b"\n")
            idx_r = buf.find(b"\r")
            if idx_n < 0 and idx_r < 0:
                break
            # 有 \n 说明是完整行（含 Windows 的 \r\n），按完整行进日志；
            # 只有独立 \r（无 \n）才是进度条覆盖帧，仅更新 step。
            if idx_n >= 0:
                idx = idx_n
                is_progress = False
            else:
                idx = idx_r
                is_progress = True
            line = buf[:idx].decode("utf-8", "replace").rstrip()
            # 跳过 \n（或 \r），并连带吞掉紧跟的 \n（处理 \r\n）
            if is_progress:
                buf = buf[idx + 1:]
            else:
                buf = buf[idx + 1:]
            if line.strip():
                if is_progress:
                    progress.set(step=line.strip()[-60:])
                else:
                    progress.append_log(line)
                    progress.set(step=line.strip()[-60:])

    try:
        while True:
            if _CANCEL_EVENT.is_set():
                progress.append_log("> 已取消")
                cancel_active_task()
                return 1
            try:
                chunk = q.get(timeout=5)
            except _queue.Empty:
                # 队列超时（无新输出）：若进程已结束且队列空则退出，否则更新耗时提示
                if p.poll() is not None:
                    break
                elapsed = int(time.time() - start_time)
                if elapsed - last_report >= 10:
                    last_report = elapsed
                    progress.set(step=f"下载中… 已用时 {elapsed} 秒（大文件无实时进度，请耐心）")
                continue
            if chunk is None:
                break
            buf += chunk
            _drain_buf()
        _drain_buf()
    except Exception as e:
        progress.append_log(f"> 读取异常: {e}")
    finally:
        try:
            p.wait(timeout=timeout) if timeout else p.wait()
        except Exception:
            pass
        _clear_active()
    return p.returncode


def _clone_runtime(progress):
    """复制项目自带 runtime → 独立环境目录（代替 venv）。

    使用 robocopy（Windows 自带，增量+跳过已存在），排除 __pycache__。
    """
    progress.set(step="复制自带 Python 运行时（约 0.6GB）…", percent=3)
    progress.append_log(f"复制 runtime: {SOURCE_RUNTIME} -> {ENV_DIR}")

    if not os.path.isfile(os.path.join(SOURCE_RUNTIME, "python.exe")):
        raise RuntimeError(f"未找到项目自带运行时: {SOURCE_RUNTIME}\\python.exe")

    # robocopy 返回码：0-7 均为成功（如 1=已复制，2=额外目录等），>=8 才失败
    rc = subprocess.run(
        ["robocopy", SOURCE_RUNTIME, ENV_DIR, "/E", "/NFL", "/NDL", "/NJH", "/NJS", "/NP",
         "/R:1", "/W:1", "/XD", "__pycache__"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    ).returncode
    if rc >= 8:
        raise RuntimeError(f"复制运行时失败（robocopy 返回码 {rc}）")

    if not os.path.isfile(_py_exe()):
        raise RuntimeError(f"复制完成但未找到 {_py_exe()}")


def _ensure_pip(progress, py):
    """确保克隆环境内有 pip（项目 runtime 通常已自带 pip）。"""
    try:
        r = _run([py, "-m", "pip", "--version"], progress, timeout=120)
        if r == 0:
            return
    except Exception:
        pass
    progress.append_log("pip 缺失，尝试用 get-pip 引导…")
    get_pip = os.path.join(SOURCE_RUNTIME, "get-pip.py")
    if os.path.isfile(get_pip):
        _run([py, get_pip], progress, timeout=600)
    else:
        raise RuntimeError("自带运行时缺少 pip 且无 get-pip.py，请重新获取完整 runtime")


def _pip_install(progress, pip_index=None):
    py = _py_exe()
    _ensure_pip(progress, py)

    idx_args = ["-i", pip_index] if pip_index else []
    progress.set(step="升级 pip…", percent=20)
    _run([py, "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel", "--progress-bar", "off",
          "--timeout", "20", "--retries", "15"] + idx_args,
         progress, timeout=600)

    progress.set(step="安装 qwen-tts 及服务依赖（含 torch，可能较慢）…", percent=30)
    progress.append_log("pip 源: " + (pip_index or "默认(官方)"))
    rc = _run([py, "-m", "pip", "install", "--progress-bar", "off", "--timeout", "20", "--retries", "15"] + DEPS + idx_args,
              progress, timeout=7200)
    if rc != 0:
        raise RuntimeError("依赖安装失败，请查看日志。可尝试切换 pip 镜像源。")


def _predownload_model(progress, model, hf_endpoint=None):
    """预下载模型权重（基准模型 + 编解码 tokenizer）到 models/ 缓存。

    用 snapshot_download 纯下载（只拉文件、不加载进内存），避免
    CPU-only torch 下 bfloat16 加载失败或 OOM。
    HF 支持断点续传（resume），中断后重新调用会从断点继续。
    """
    py = _py_exe()
    env = {
        # 拉长超时、禁用 xet（xet 在某些网络下会中途断开），稳定下载
        "HF_HUB_DOWNLOAD_TIMEOUT": "120",
        "HF_HUB_ENABLE_HF_TRANSFER": "0",
        "HF_XET_DISABLED": "1",
    }
    if hf_endpoint:
        env["HF_ENDPOINT"] = hf_endpoint
        progress.append_log("HF 端点: " + hf_endpoint)

    progress.set(step=f"预下载模型 {model}（约 6-7GB，支持断点续传，请耐心等待）…", percent=55)
    script = (
        "from huggingface_hub import snapshot_download\n"
        f"p1 = snapshot_download(repo_id='{model}', cache_dir=r'{MODELS_DIR}', "
        "resume_download=True, max_workers=4)\n"
        "print('DOWN_BASE_OK', p1)\n"
        f"p2 = snapshot_download(repo_id='{TOKENIZER_MODEL}', cache_dir=r'{MODELS_DIR}', "
        "resume_download=True, max_workers=4)\n"
        "print('DOWN_TOK_OK', p2)\n"
        "print('MODEL_DOWNLOAD_OK')\n"
    )
    rc = _run([py, "-c", script], progress, timeout=7200, env=env)
    if rc != 0:
        raise RuntimeError("模型下载失败，请检查网络。可设置 GWC_HF_ENDPOINT=https://hf-mirror.com 重试，已下载部分会续传。")


# ============================================================
# ModelScope 下载器（国内备选源，应对 HF/hf-mirror 被墙或超时）
# 用 ModelScope 官方 API 下载，放入 HF 兼容的 cache 目录结构，
# 使 qwen-tts 的 from_pretrained(cache_dir=models) 能直接识别。
# ============================================================
MODELSCOPE_BASE = "https://www.modelscope.cn"

_MODELSCOPE_SCRIPT = r'''
import os, sys, json, urllib.request, urllib.error, shutil, time

BASE = "https://www.modelscope.cn"
CACHE = sys.argv[1]
REPOS = sys.argv[2].split(",")   # 逗号分隔的 repo id（org/name）
UA = {"User-Agent": "Mozilla/5.0"}

def _get(url, timeout=60):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=timeout)

def list_files(repo):
    url = f"{BASE}/api/v1/models/{repo}/repo/files?Recursive=true"
    d = json.load(_get(url))
    return d["Data"]["Files"]

def hf_cache_dir(repo):
    org, name = repo.split("/", 1)
    return os.path.join(CACHE, f"models--{org}--{name}")

def download_with_resume(url, dest, retries=3):
    """断点续传下载：.part 保留已下载部分，中断后用 Range 续传。"""
    tmp = dest + ".part"
    for attempt in range(retries):
        try:
            existing = os.path.getsize(tmp) if os.path.isfile(tmp) else 0
            headers = dict(UA)
            if existing > 0:
                headers["Range"] = f"bytes={existing}-"
            req = urllib.request.Request(url, headers=headers)
            resp = urllib.request.urlopen(req, timeout=120)
            mode = "ab" if existing > 0 else "wb"
            if existing > 0 and resp.status == 206:
                pass  # Range 续传
            elif existing > 0 and resp.status == 200:
                # 服务器不支持 Range，重新下载
                existing = 0
                mode = "wb"
            with open(tmp, mode) as out:
                shutil.copyfileobj(resp, out, length=1024*1024)
            os.replace(tmp, dest)
            return True
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            print(f"      重试 {attempt+1}/{retries}: {e}", flush=True)
            time.sleep(3)
    return False

for repo in REPOS:
    org, name = repo.split("/", 1)
    print(f">> 下载 {repo} (ModelScope)")
    files = list_files(repo)
    rev = files[0]["Revision"]
    snap = os.path.join(hf_cache_dir(repo), "snapshots", rev)
    os.makedirs(snap, exist_ok=True)
    total = len(files)
    for i, f in enumerate(files):
        p = f["Path"]
        dest = os.path.join(snap, p)
        if os.path.isfile(dest) and os.path.getsize(dest) > 0:
            print(f"  [{i+1}/{total}] 已存在 {p}", flush=True)
            continue
        parent = os.path.dirname(dest)
        if parent:
            os.makedirs(parent, exist_ok=True)
        url = f"{BASE}/models/{repo}/resolve/{rev}/{p}"
        print(f"  [{i+1}/{total}] 下载 {p}", flush=True)
        ok = download_with_resume(url, dest)
        if ok:
            print(f"  完成 {p} ({os.path.getsize(dest)//1024//1024}MB)", flush=True)
        else:
            print(f"  失败 {p}（已保留 .part，下次续传）", flush=True)
    refs = os.path.join(hf_cache_dir(repo), "refs")
    os.makedirs(refs, exist_ok=True)
    with open(os.path.join(refs, "main"), "w") as fh:
        fh.write(rev)
    print(f">> {repo} 完成, revision={rev}")

print("MODELSCOPE_DOWNLOAD_OK")
'''


def _predownload_model_modelscope(progress, model, tokenizer=None):
    """用 ModelScope 国内源下载模型（HF/hf-mirror 不可用时的备选）。"""
    py = _py_exe()
    tokenizer = tokenizer or TOKENIZER_MODEL
    repos = ",".join([model, tokenizer])

    progress.set(step="用 ModelScope 国内源下载模型（约 6-7GB，请耐心等待）…", percent=55)
    progress.append_log("源: ModelScope (www.modelscope.cn)")
    rc = _run([py, "-c", _MODELSCOPE_SCRIPT, MODELS_DIR, repos], progress, timeout=7200)
    if rc != 0:
        raise RuntimeError("ModelScope 下载失败，请查看日志重试（支持断点续传）。")


def is_model_ready(model=None):
    """判断模型权重是否已完整下载（base + tokenizer 都要有 .safetensors 权重）。

    遍历该模型的所有 snapshot 子目录，只要任一目录里存在非空的 .safetensors
    权重文件即视为就绪。带缓存（文件遍历较慢）。
    """
    def _probe():
        base = model or os.environ.get("GWC_QWEN_TTS_MODEL") or DEFAULT_MODEL
        tok = TOKENIZER_MODEL
        for mid in (base, tok):
            if not _has_weight_in_snapshots(mid):
                return False
        return True
    return _cached("is_model_ready", _probe)


def _has_weight_in_snapshots(model_id):
    """任一 snapshot 目录下存在非空 .safetensors 即返回 True。"""
    parts = model_id.split("/")
    name = parts[-1] if len(parts) > 1 else model_id
    org = parts[0] if len(parts) > 1 else "Qwen"
    cache_dir_name = f"models--{org}--{name}"
    snapshots = os.path.join(MODELS_DIR, cache_dir_name, "snapshots")
    if not os.path.isdir(snapshots):
        return False
    for sub in os.listdir(snapshots):
        snap_sub = os.path.join(snapshots, sub)
        if not os.path.isdir(snap_sub):
            continue
        for root, _, files in os.walk(snap_sub):
            for f in files:
                if f.endswith(".safetensors") and os.path.getsize(os.path.join(root, f)) > 0:
                    return True
    return False


def download_model(hf_endpoint=None, model=None, progress=None, source="auto"):
    """独立下载模型权重（不重装环境）。供「模型下载」按钮单独调用。

    source: "auto"（先 HF/hf-mirror，失败回退 ModelScope）/ "hf" / "modelscope"
    """
    # 模型下载用独立进度对象，避免与「一键安装」的 PROGRESS 互相覆盖
    progress = progress or MODEL_PROGRESS
    progress.reset()
    progress.set(running=True, started_at=time.time(), step="准备下载模型…", percent=1)

    hf_endpoint = hf_endpoint or os.environ.get("GWC_HF_ENDPOINT")
    model = model or os.environ.get("GWC_QWEN_TTS_MODEL") or DEFAULT_MODEL

    try:
        if not is_installed():
            raise RuntimeError("Qwen3-TTS 环境尚未安装，请先点「一键安装环境」")
        if source == "modelscope":
            _predownload_model_modelscope(progress, model)
        elif source == "hf":
            _predownload_model(progress, model, hf_endpoint)
        else:
            # auto：先 HF，失败回退 ModelScope
            try:
                _predownload_model(progress, model, hf_endpoint)
            except Exception:
                progress.append_log("> HF 下载失败，改用 ModelScope 国内源…")
                _predownload_model_modelscope(progress, model)
        progress.set(step="模型下载完成", percent=100, ok=True)
    except Exception as e:
        progress.set(error=str(e), ok=False)
    finally:
        progress.set(running=False, done=True)

    return progress.snapshot()


def install(pip_index=None, hf_endpoint=None, with_model=False, model=None, progress=None, torch_variant=None):
    """一键安装：克隆 runtime → pip → 切换 torch →（可选）预下载模型。

    pip_index    : 自定义 pip 镜像源（默认清华）
    hf_endpoint  : 自定义 HF 端点（默认官方；大陆可设 hf-mirror）
    with_model   : 是否顺带预下载模型权重
    model        : Base 模型 ID（默认 1.7B）
    torch_variant: torch 变体 id（cpu/cu126/cu124/cu121），装完依赖后立即切换
    """
    progress = progress or PROGRESS
    progress.reset()
    progress.set(running=True, started_at=time.time(), step="准备安装…", percent=1)

    pip_index = pip_index or os.environ.get("GWC_PIP_INDEX") or DEFAULT_PIP_INDEX
    hf_endpoint = hf_endpoint or os.environ.get("GWC_HF_ENDPOINT")
    model = model or os.environ.get("GWC_QWEN_TTS_MODEL") or DEFAULT_MODEL

    try:
        if is_installed():
            progress.set(step="环境已就绪，跳过安装", percent=100, ok=True)
        else:
            _clone_runtime(progress)
            _pip_install(progress, pip_index)
            progress.set(step="依赖安装完成", percent=50, ok=True)

        # 首次安装时按用户选择切换 torch 后端（非 cpu 时切换到 CUDA 版）
        if torch_variant and torch_variant != "cpu":
            progress.set(step=f"切换 torch 到 {torch_variant}…", percent=60)
            try:
                install_torch_variant(torch_variant, progress=None)  # 用独立进度，避免覆盖
            except Exception as e:
                progress.append_log(f"⚠ torch 切换失败: {e}（可稍后在设置页手动切换）")

        if with_model:
            _predownload_model(progress, model, hf_endpoint)
            progress.set(step="模型下载完成", percent=100, ok=True, done=True)
        else:
            progress.set(step="安装完成（模型将在首次启动时按需下载）", percent=100, ok=True, done=True)
    except Exception as e:
        progress.set(error=str(e), ok=False)
    finally:
        progress.set(running=False, done=True)

    return progress.snapshot()


# ============================================================
# torch 版本管理（CUDA 各版本 / CPU 切换、卸载、检查更新）
# ============================================================
# 实测结论（重要）：
#   - 标准 PyPI（清华源等）的 Windows torch wheel 是【纯 CPU 版】（124MB，无 nvidia 依赖），
#     torch.cuda.is_available() 永远 False。
#   - 要获得 CUDA 支持，必须装 +cuXXX 后缀的 wheel（约 2.4GB）。
#   - download.pytorch.org 国内直连下载大文件会在 ~245MB 处断连停滞，
#     实测 SJTUG（上海交大）镜像 https://mirrors.sjtug.sjtu.edu.cn/pytorch-wheels/ 可用。
# 环境变量 GWC_TORCH_MIRROR 可覆盖镜像 base（末尾不含 /cuXXX）。
DEFAULT_TORCH_MIRROR = os.environ.get(
    "GWC_TORCH_MIRROR", "https://mirrors.sjtug.sjtu.edu.cn/pytorch-wheels"
).rstrip("/")

# GPU 类型标记：nvidia=CUDA（需 NVIDIA 显卡）；directml=DirectML（AMD/Intel 核显+独显，实验性）
TORCH_VARIANTS = [
    {"id": "cu126", "label": "CUDA 12.6（NVIDIA GPU）", "cu": "cu126", "gpu_type": "nvidia",
     "desc": "torch 2.14+cu126，需 NVIDIA 显卡，约 2.4GB"},
    {"id": "cu124", "label": "CUDA 12.4（NVIDIA GPU）", "cu": "cu124", "gpu_type": "nvidia",
     "desc": "torch 2.6+cu124，需 NVIDIA 显卡，约 2.4GB"},
    {"id": "cu121", "label": "CUDA 12.1（NVIDIA GPU）", "cu": "cu121", "gpu_type": "nvidia",
     "desc": "torch 2.5+cu121，需 NVIDIA 显卡，约 2.3GB"},
    {"id": "directml", "label": "DirectML（AMD/Intel 核显+独显）", "kind": "directml", "gpu_type": "directml",
     "desc": "torch-directml，支持 AMD/Intel/NVIDIA 核显与独显（实验性，兼容性待验证）"},
    {"id": "cpu", "label": "仅 CPU", "index_url": "", "use_pip_index": True, "gpu_type": "cpu",
     "desc": "纯 CPU 版（标准 PyPI，124MB，快，无 GPU 加速）"},
]

# torch 操作独立进度（避免与安装/下载的 PROGRESS 互相覆盖）
TORCH_PROGRESS = QwenInstallProgress()
# 更新包操作独立进度
UPDATE_PROGRESS = QwenInstallProgress()


def get_torch_info(force=False):
    """探测当前 torch 版本与后端（cpu/cuda）。带缓存，force=True 强制重新探测。"""
    def _probe():
        py = _py_exe()
        if not os.path.isfile(py):
            return {"installed": False, "torch_version": None, "backend": None, "cuda_available": False}
        try:
            code = (
                "import torch\n"
                "print(torch.__version__)\n"
                "try:\n"
                "    import torch_directml\n"
                "    print('DIRECTML' if torch_directml.is_available() else ('CUDA' if torch.cuda.is_available() else 'CPU'))\n"
                "except Exception:\n"
                "    print('CUDA' if torch.cuda.is_available() else 'CPU')\n"
                "print(torch.version.cuda or '')\n"
            )
            r = subprocess.run([py, "-c", code], capture_output=True, text=True, timeout=15)
            if r.returncode != 0:
                return {"installed": False, "torch_version": None, "backend": None, "cuda_available": False}
            lines = r.stdout.strip().splitlines()
            torch_version = lines[0].strip() if len(lines) > 0 else None
            backend = lines[1].strip() if len(lines) > 1 else "CPU"
            cuda = lines[2].strip() if len(lines) > 2 else ""
            # 从后端判断 variant：DIRECTML / CUDA(gpu) / CPU
            if backend == "DIRECTML":
                variant = "directml"
            elif backend == "CUDA" or "+cu" in (torch_version or ""):
                variant = "gpu"
            else:
                variant = "cpu"
            return {
                "installed": True,
                "torch_version": torch_version,
                "backend": backend,
                "cuda_version": cuda,
                "cuda_available": backend == "CUDA",
                "variant": variant,
            }
        except Exception as e:
            return {"installed": False, "torch_version": None, "backend": None, "cuda_available": False, "error": str(e)}
    if force:
        _ENV_CACHE.pop("torch_info", None)
    return _cached("torch_info", _probe)


def _torch_variant(variant_id):
    for v in TORCH_VARIANTS:
        if v["id"] == variant_id:
            return v
    return None


def install_torch_variant(variant_id, progress=None, pip_index=None, mirror=None):
    """切换 torch 到指定变体（覆盖安装，不先卸载旧版，失败不破坏旧环境）。

    variant_id: "cu126"/"cu124"/"cu121"/"directml"/"cpu"。
    mirror: 镜像 id（sjtug/official/aliyun），用于 CUDA 下载；不传用 DEFAULT_TORCH_MIRROR。
    """
    progress = progress or TORCH_PROGRESS
    progress.reset()
    progress.set(running=True, started_at=time.time(), step="准备切换 torch…", percent=1)

    v = _torch_variant(variant_id)
    if v is None:
        progress.set(error=f"未知的 torch 变体: {variant_id}", ok=False, running=False, done=True)
        return progress.snapshot()

    py = _py_exe()
    if not os.path.isfile(py):
        progress.set(error="Qwen3-TTS 环境尚未安装", ok=False, running=False, done=True)
        return progress.snapshot()

    pip_index = pip_index or os.environ.get("GWC_PIP_INDEX") or DEFAULT_PIP_INDEX

    # 解析镜像 base：优先传入 mirror id，其次环境变量 GWC_TORCH_MIRROR
    mirror_base = DEFAULT_TORCH_MIRROR
    if mirror:
        for m in TORCH_MIRRORS:
            if m["id"] == mirror:
                mirror_base = m["base"]
                break
    else:
        env_m = os.environ.get("GWC_TORCH_MIRROR")
        if env_m:
            mirror_base = env_m.rstrip("/")

    try:
        # 直接覆盖安装（不先卸载）：pip 会先下载完 wheel 再替换旧版，
        # 下载失败时旧 torch 仍保留，避免「切失败就没得用、还得重下」。
        # 关键：加 --timeout 20 --retries 15，让 pip 在下载断连后自动用
        # Range 续传重试（实测国内网络下大文件会反复断连，续传可断断续续下完）。
        if v.get("kind") == "directml":
            # DirectML：AMD/Intel 核显+独显（也兼容 NVIDIA）。装 torch-directml，
            # 它依赖 CPU 版 torch 并附带 DirectML 后端。
            progress.set(step=f"安装 {v['label']}（torch-directml，约 1-2GB，请耐心等待）…", percent=20)
            progress.append_log("DirectML 后端（AMD/Intel/NVIDIA 通用，实验性）")
            cmd = [py, "-m", "pip", "install", "torch-directml",
                   "-i", pip_index, "--timeout", "20", "--retries", "15"]
        elif v.get("use_pip_index"):
            # CPU 版：标准 PyPI（清华源，快）
            progress.append_log("index-url: " + pip_index + "（CPU 版）")
            cmd = [py, "-m", "pip", "install", "--force-reinstall", "torch", "torchaudio",
                   "-i", pip_index, "--timeout", "20", "--retries", "15"]
        else:
            # CUDA 版：选中的镜像（默认 SJTUG 上海交大，国内快）
            progress.set(step=f"安装 {v['label']}（约 2.4GB，支持断点续传，请耐心等待）…", percent=20)
            idx = f"{mirror_base}/{v['cu']}"
            progress.append_log("index-url: " + idx)
            cmd = [py, "-m", "pip", "install", "--force-reinstall", "torch", "torchaudio",
                   "--index-url", idx, "--timeout", "20", "--retries", "15"]
        rc = _run(cmd, progress, timeout=7200)
        if rc != 0:
            raise RuntimeError(f"安装 {v['label']} 失败，请查看日志。可换镜像或设置环境变量 GWC_TORCH_MIRROR 后重试。")

        # 校验
        info = get_torch_info(force=True)
        progress.set(step=f"torch 切换完成: {info.get('torch_version')}", percent=100, ok=True)
    except Exception as e:
        progress.set(error=str(e), ok=False)
    finally:
        progress.set(running=False, done=True)

    return progress.snapshot()


def uninstall_torch(progress=None):
    """卸载 torch/torchaudio（供用户清理不需要的版本）。"""
    progress = progress or TORCH_PROGRESS
    progress.reset()
    progress.set(running=True, started_at=time.time(), step="准备卸载 torch…", percent=5)

    py = _py_exe()
    if not os.path.isfile(py):
        progress.set(error="Qwen3-TTS 环境尚未安装", ok=False, running=False, done=True)
        return progress.snapshot()

    try:
        rc = _run([py, "-m", "pip", "uninstall", "-y", "torch", "torchaudio"], progress, timeout=600)
        if rc != 0:
            raise RuntimeError("卸载 torch 失败")
        progress.set(step="已卸载 torch / torchaudio", percent=100, ok=True)
    except Exception as e:
        progress.set(error=str(e), ok=False)
    finally:
        progress.set(running=False, done=True)

    return progress.snapshot()


def update_package(pkg, pip_index=None, progress=None):
    """升级指定包到最新版（供「检查更新」的「更新」按钮调用）。"""
    progress = progress or UPDATE_PROGRESS
    progress.reset()
    progress.set(running=True, started_at=time.time(), step=f"准备升级 {pkg}…", percent=2)

    py = _py_exe()
    if not os.path.isfile(py):
        progress.set(error="Qwen3-TTS 环境尚未安装", ok=False, running=False, done=True)
        return progress.snapshot()

    pip_index = pip_index or os.environ.get("GWC_PIP_INDEX") or DEFAULT_PIP_INDEX

    try:
        progress.set(step=f"升级 {pkg} 到最新版…", percent=15)
        cmd = [py, "-m", "pip", "install", "--upgrade", pkg, "-i", pip_index, "--progress-bar", "off"]
        rc = _run(cmd, progress, timeout=3600)
        if rc != 0:
            raise RuntimeError(f"升级 {pkg} 失败，请查看日志。")
        progress.set(step=f"{pkg} 升级完成", percent=100, ok=True)
    except Exception as e:
        progress.set(error=str(e), ok=False)
    finally:
        progress.set(running=False, done=True)

    return progress.snapshot()


def check_updates():
    """检查核心依赖是否有更新（qwen-tts / torch / transformers / torchaudio）。

    返回每个包：当前版本 vs 最新版本 + 是否可更新。
    注意：torch 的「最新」只在对应 index-url 下才有意义，这里统一查
    download.pytorch.org/whl/cu126 源下的最新 CPU/CUDA 版本。
    """
    py = _py_exe()
    if not os.path.isfile(py):
        return {"ok": False, "msg": "环境尚未安装", "items": []}

    import json as _json
    checks = []
    # 查 PyPI（清华源）上的最新版本
    def _latest_pypi(pkg):
        try:
            r = subprocess.run(
                [py, "-m", "pip", "index", "versions", pkg, "-i", DEFAULT_PIP_INDEX],
                capture_output=True, text=True, timeout=60,
            )
            out = r.stdout or ""
            # 形如 "pkg (x.y.z)\nAvailable versions: a, b, c"
            for line in out.splitlines():
                if line.strip().startswith("INSTALLED:"):
                    pass
                elif line.strip().startswith("LATEST:"):
                    return line.split(":", 1)[1].strip()
                elif line.strip().startswith(pkg + " ("):
                    return line.strip().split("(", 1)[1].rstrip(")")
                elif line.strip().startswith("Available versions:"):
                    rest = line.split(":", 1)[1].strip()
                    return rest.split(",")[0].strip()
            return None
        except Exception:
            return None

    def _current(pkg):
        # 用 importlib.metadata 按分发名查版本（能正确处理 qwen-tts 连字符名等）
        try:
            code = (
                "import importlib.metadata as md\n"
                f"print(md.version({pkg!r}))\n"
            )
            r = subprocess.run([py, "-c", code], capture_output=True, text=True, timeout=60)
            return (r.stdout or "").strip() if r.returncode == 0 else None
        except Exception:
            return None

    items = []
    # transformers 被 qwen-tts 锁定版本，不可单独升级（升级会破坏 qwen-tts）
    locked = {"transformers": True}
    for pkg, label in (("qwen-tts", "qwen-tts"), ("torch", "torch"), ("transformers", "transformers"), ("torchaudio", "torchaudio")):
        cur = _current(pkg)
        latest = _latest_pypi(pkg)
        items.append({
            "package": pkg,
            "label": label,
            "current": cur,
            "latest": latest,
            "update_available": bool(cur and latest and cur != latest),
            "locked": locked.get(pkg, False),
        })

    return {"ok": True, "items": items}


# 查询 torch 各变体最新可用版本（供「检查更新」与前端展示）
def torch_variants_with_info():
    """返回 TORCH_VARIANTS + 每个变体的最新 torch 版本 + 当前是否为该变体。"""
    info = get_torch_info()
    result = []
    for v in TORCH_VARIANTS:
        result.append({
            **v,
            "current": info.get("torch_version") if info.get("variant") == _variant_of(v["id"]) else None,
            "is_current_variant": info.get("variant") == _variant_of(v["id"]),
        })
    return {"torch_info": info, "variants": result}


def _variant_of(variant_id):
    # gpu/cpu 直接返回；兼容旧的 cuXXX 写法
    return "gpu" if variant_id.startswith("cu") else variant_id


# ============================================================
# 硬件检测（GPU 型号/显存，含核显与多卡）
# ============================================================
def detect_hardware():
    """检测本机 GPU 配置（NVIDIA/AMD/Intel 核显+独显），供前端展示与自动隐藏不支持的 torch 环境。"""
    gpus = []
    seen_names = set()

    def _add(vendor, index, name, vram_mb):
        key = (name or "").strip().lower()
        if key and key not in seen_names:
            seen_names.add(key)
            gpus.append({"vendor": vendor, "index": str(index), "name": name, "vram_mb": int(vram_mb or 0)})

    # 1) NVIDIA 独显：nvidia-smi（信息最准）
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            for line in (r.stdout or "").strip().splitlines():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 3:
                    idx = parts[0]
                    name = parts[1]
                    try:
                        vram = int(float(parts[2]))
                    except Exception:
                        vram = 0
                    _add("NVIDIA", idx, name, vram)
    except Exception:
        pass

    # 2) 全部显卡（含核显）：PowerShell CIM（Windows）
    try:
        ps = "Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM | ConvertTo-Json -Compress"
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, text=True, timeout=15)
        if r.returncode == 0 and (r.stdout or "").strip():
            import json as _json
            try:
                data = _json.loads(r.stdout)
            except Exception:
                data = []
            items = data if isinstance(data, list) else [data]
            for it in items:
                name = (it.get("Name") or "").strip()
                raw = it.get("AdapterRAM") or 0
                lower = name.lower()
                if "amd" in lower or "radeon" in lower:
                    vendor = "AMD"
                elif "intel" in lower:
                    vendor = "Intel"
                elif "nvidia" in lower:
                    vendor = "NVIDIA"
                else:
                    vendor = "Other"
                vram_mb = int(raw) // 1024 // 1024 if isinstance(raw, int) and raw > 0 else 0
                _add(vendor, "", name, vram_mb)
    except Exception:
        pass

    # 3) 判断是否有 NVIDIA / AMD 独显
    has_nvidia = any(g["vendor"] == "NVIDIA" for g in gpus)
    has_amd = any(g["vendor"] == "AMD" for g in gpus)
    multi_gpu = len(gpus) > 1

    return {
        "gpus": gpus,
        "has_nvidia": has_nvidia,
        "has_amd": has_amd,
        "multi_gpu": multi_gpu,
        "torch": get_torch_info(),
    }


# ============================================================
# Qwen3-TTS 模型管理（切换型号 / 卸载）
# ============================================================
_MODEL_CONFIG_PATH = os.path.join(QWEN_TTS_DIR, "current_model.txt")


def get_current_model():
    """当前使用的 Base 模型 id（配置文件 > 环境变量 > 默认 1.7B）。"""
    try:
        if os.path.isfile(_MODEL_CONFIG_PATH):
            with open(_MODEL_CONFIG_PATH, "r", encoding="utf-8") as f:
                v = f.read().strip()
            if v:
                return v
    except Exception:
        pass
    return os.environ.get("GWC_QWEN_TTS_MODEL") or DEFAULT_MODEL


def switch_model(model_id):
    """切换当前使用的 Base 模型（写入配置文件，下次启动生效）。"""
    valid = any(m["id"] == model_id for m in QWEN3_TTS_MODELS)
    if not valid:
        raise RuntimeError(f"未知的模型型号: {model_id}")
    with open(_MODEL_CONFIG_PATH, "w", encoding="utf-8") as f:
        f.write(model_id)
    # 清除模型就绪缓存，让下次 is_model_ready 重新探测
    _ENV_CACHE.pop("is_model_ready", None)
    return {"ok": True, "model": model_id}


def list_qwen3_models():
    """返回所有可选 Qwen3-TTS 模型型号 + 各自下载/当前状态。"""
    cur = get_current_model()
    result = []
    for m in QWEN3_TTS_MODELS:
        result.append({
            **m,
            "downloaded": _has_weight_in_snapshots(m["id"]),
            "is_current": m["id"] == cur,
        })
    return {
        "models": result,
        "current": cur,
        "tokenizer": TOKENIZER_MODEL,
        "tokenizer_ready": _has_weight_in_snapshots(TOKENIZER_MODEL),
    }


def uninstall_model(model_id):
    """卸载指定模型的本地缓存目录（不影响 tokenizer）。"""
    if model_id == TOKENIZER_MODEL:
        raise RuntimeError("tokenizer 是必需配套，不可卸载")
    parts = model_id.split("/")
    name = parts[-1] if len(parts) > 1 else model_id
    org = parts[0] if len(parts) > 1 else "Qwen"
    cache_dir = os.path.join(MODELS_DIR, f"models--{org}--{name}")
    if os.path.isdir(cache_dir):
        shutil.rmtree(cache_dir, ignore_errors=True)
    _ENV_CACHE.pop("is_model_ready", None)
    return {"ok": True, "model": model_id, "removed": not os.path.isdir(cache_dir)}