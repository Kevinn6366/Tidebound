import React from 'react';
import { useApp } from '../../contexts/AppContext';
import SettingToggle from '../ui/SettingToggle';
import SettingSlider from '../ui/SettingSlider';
import SettingSectionTitle from '../ui/SettingSectionTitle';
import { Upload, Trash2, Music, AlertCircle, Mic2, Play, Square, RefreshCw, Loader2, CheckCircle, XCircle, Download, Globe, X, Pencil } from 'lucide-react';
import { playClickSound } from '../../utils/uiFeedback';

export default function SoundTab() {
  const { settings, setSettings, handleBgmUpload, removeBgm, bgmList, currentBgmIndex, setCurrentBgmIndex, isBgmPlaying, toggleBgm } = useApp();
  const [soundMsg, setSoundMsg] = React.useState(null);

  // ---- 内置配音 (GPT-SoVITS / Qwen3-TTS) 引擎切换 ----
  const [ttsStatus, setTtsStatus] = React.useState(null);   // null = 尚未探测
  const [ttsVoices, setTtsVoices] = React.useState([]);
  const [ttsBusy, setTtsBusy] = React.useState(false);
  const [ttsStarting, setTtsStarting] = React.useState(false); // 启动中（模型加载），此时显示「停止」按钮允许中断
  const [ttsMsg, setTtsMsg] = React.useState('');
  const [voiceBusy, setVoiceBusy] = React.useState('');
  const [emotions, setEmotions] = React.useState([]);
  const ttsPollRef = React.useRef(null);     // 启动轮询 timer

  // ---- Qwen3-TTS 专用状态 ----
  const [qwenStatus, setQwenStatus] = React.useState(null);
  const [qwenVoices, setQwenVoices] = React.useState([]);
  const [qwenBusy, setQwenBusy] = React.useState(false);
  const [qwenStarting, setQwenStarting] = React.useState(false);
  const [qwenMsg, setQwenMsg] = React.useState('');
  const [qwenVoiceBusy, setQwenVoiceBusy] = React.useState('');
  const [qwenInstall, setQwenInstall] = React.useState(null);   // 安装进度
  const [qwenInstallPipIndex, setQwenInstallPipIndex] = React.useState('');
  const [qwenInstallHf, setQwenInstallHf] = React.useState('');
  const [qwenInstallWithModel, setQwenInstallWithModel] = React.useState(false);
  const [qwenInstallTorchVariant, setQwenInstallTorchVariant] = React.useState('cu126'); // 首次安装选的 torch 变体
  const qwenPollRef = React.useRef(null);   // 启动轮询 timer
  // 模型下载（独立于环境安装）
  const [qwenModel, setQwenModel] = React.useState(null);       // { env_installed, model_ready }
  const [qwenModelDl, setQwenModelDl] = React.useState(null);   // 下载进度
  const [showModelDlg, setShowModelDlg] = React.useState(false); // 模型下载弹窗
  const [modelHfEndpoint, setModelHfEndpoint] = React.useState('');
  const [modelSource, setModelSource] = React.useState('auto');   // auto / hf / modelscope
  // torch 版本管理 / 检查更新
  const [torchInfo, setTorchInfo] = React.useState(null);        // { torch_info, variants }
  const [torchOp, setTorchOp] = React.useState(null);            // torch 安装/卸载进度
  const [showTorchDlg, setShowTorchDlg] = React.useState(false); // torch 切换弹窗
  const [updates, setUpdates] = React.useState(null);           // 检查更新结果
  const [checkingUpdate, setCheckingUpdate] = React.useState(false);
  const [torchMirrors, setTorchMirrors] = React.useState([]);   // torch 镜像列表
  const [torchMirror, setTorchMirror] = React.useState('sjtug'); // 选中的镜像
  // 硬件检测 + 手动纠错
  const [hardware, setHardware] = React.useState(null);          // { gpus, has_nvidia, has_amd, multi_gpu, torch }
  const [manualGpu, setManualGpu] = React.useState('');          // 手动选择的 GPU 类型
  // Qwen3 模型管理
  const [qwenModels, setQwenModels] = React.useState(null);      // { models, current, tokenizer, tokenizer_ready }
  // 文档弹窗
  const [showDoc, setShowDoc] = React.useState(null);            // 'sovits' | 'qwen' | null
  // Qwen3 音色快速添加（参考音频 + 文本填写）
  const [qwenVoiceForm, setQwenVoiceForm] = React.useState({ id: '', text: '' });
  const [qwenVoiceFile, setQwenVoiceFile] = React.useState(null); // 上传的参考音频文件
  const [qwenVoiceSaving, setQwenVoiceSaving] = React.useState(false);
  // GPT-SoVITS 模型快速添加
  const [sovitsModelForm, setSovitsModelForm] = React.useState({ name: '', version: 'v2ProPlus', ckpt: '', pth: '', ref_audio: '', ref_text: '' });
  const [sovitsModelSaving, setSovitsModelSaving] = React.useState(false);

  const fetchTtsStatus = React.useCallback(async () => {
    try {
      const s = await fetch('/api/tts/status').then(r => r.json());
      setTtsStatus(s);
      return s;
    } catch { setTtsStatus({ ok: false, running: false }); return null; }
  }, []);

  const fetchVoices = React.useCallback(async () => {
    try {
      const d = await fetch('/api/tts/voices').then(r => r.json());
      setTtsVoices(Array.isArray(d.voices) ? d.voices : []);
    } catch { setTtsVoices([]); }
  }, []);

  React.useEffect(() => {
    fetchTtsStatus().then(s => { if (s?.running) fetchVoices(); });
  }, [fetchTtsStatus, fetchVoices]);

  const startTts = async () => {
    setTtsBusy(true); setTtsStarting(true); setTtsMsg('正在启动，首次加载模型约需 10-60 秒…');
    try {
      const r = await fetch('/api/tts/start', { method: 'POST' }).then(r => r.json());
      if (!r.ok) { setTtsMsg(r.msg || '启动失败'); setTtsBusy(false); setTtsStarting(false); return; }
      setTtsBusy(false);
      // 模型加载较慢，轮询到就绪为止（最多约 90 秒），期间可点「停止」中断
      let i = 0;
      ttsPollRef.current = setInterval(async () => {
        i++;
        const s = await fetchTtsStatus();
        if (s?.running) {
          clearInterval(ttsPollRef.current); ttsPollRef.current = null;
          setTtsMsg('内置配音已就绪'); setTtsStarting(false); await fetchVoices();
        } else if (i >= 45) {
          clearInterval(ttsPollRef.current); ttsPollRef.current = null;
          setTtsMsg('启动超时，请查看 TTS 日志'); setTtsStarting(false);
        }
      }, 2000);
    } catch (e) { setTtsMsg('启动失败: ' + e.message); setTtsBusy(false); setTtsStarting(false); }
  };

  const stopTts = async () => {
    // 停止进行中的启动轮询
    if (ttsPollRef.current) { clearInterval(ttsPollRef.current); ttsPollRef.current = null; }
    setTtsStarting(false);
    setTtsBusy(true); setTtsMsg('正在停止…');
    try {
      const r = await fetch('/api/tts/stop', { method: 'POST' }).then(r => r.json());
      setTtsMsg(r.msg || '');
      await fetchTtsStatus();
    } catch (e) { setTtsMsg('停止失败: ' + e.message); }
    setTtsBusy(false);
  };

  // ---- 按需安装（分发包不含推理代码与模型，首次使用时从本机 GPT-SoVITS 导入）----
  const [instSources, setInstSources] = React.useState(null);
  const [instPath, setInstPath] = React.useState('');
  const [instVoices, setInstVoices] = React.useState([]);
  const [instPicked, setInstPicked] = React.useState({});
  const [instProg, setInstProg] = React.useState(null);
  const [instScanning, setInstScanning] = React.useState(false);

  const scanSources = async (manual) => {
    setInstScanning(true);
    try {
      const q = manual ? `?path=${encodeURIComponent(manual)}` : '';
      const d = await fetch('/api/tts/install/sources' + q).then(r => r.json());
      setInstSources(d.sources || []);
      if (d.sources?.length) {
        const p = d.sources[0].path;
        setInstPath(p);
        loadInstVoices(p);
      }
    } catch { setInstSources([]); }
    setInstScanning(false);
  };

  const loadInstVoices = async (p) => {
    try {
      const d = await fetch(`/api/tts/install/voices?path=${encodeURIComponent(p)}`).then(r => r.json());
      setInstVoices(d.voices || []);
      // 默认勾选每个角色轮次最高的一组，避免一次拷贝几 GB
      const best = {};
      (d.voices || []).forEach(v => {
        const role = v.file.replace(/[-_]e\d+(_s\d+)?\.(ckpt|pth)$/i, '');
        const key = `${v.kind}:${role}`;
        const ep = parseInt((v.file.match(/[-_]e(\d+)/) || [])[1] || '0', 10);
        if (!best[key] || ep > best[key].ep) best[key] = { ep, rel: v.rel };
      });
      const picked = {};
      Object.values(best).forEach(b => { picked[b.rel] = true; });
      setInstPicked(picked);
    } catch { setInstVoices([]); }
  };

  const startInstall = async () => {
    const voices = instVoices.filter(v => instPicked[v.rel])
      .map(v => ({ kind: v.kind, dir: v.dir, file: v.file }));
    // 依据勾选的音色目录推断需要哪些底模，避免把所有版本都拷进来
    const versions = [];
    voices.forEach(v => {
      if (/v2ProPlus/i.test(v.dir)) versions.push('v2ProPlus');
      else if (/v2Pro/i.test(v.dir)) versions.push('v2Pro');
      else if (/v4/i.test(v.dir)) versions.push('v4');
    });
    const r = await fetch('/api/tts/install', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source: instPath, voices, versions: [...new Set(versions)] })
    }).then(r => r.json());
    if (!r.ok) { setTtsMsg(r.msg); return; }
    setInstProg({ running: true, percent: 0, step: '开始…' });
    const timer = setInterval(async () => {
      try {
        const p = await fetch('/api/tts/install/progress').then(r => r.json());
        setInstProg(p);
        if (p.done) {
          clearInterval(timer);
          setTtsMsg(p.ok ? '安装完成，可以启动内置配音了' : ('安装失败: ' + p.error));
          if (p.ok) { setInstSources(null); await fetchTtsStatus(); }
        }
      } catch { clearInterval(timer); }
    }, 1000);
  };

  const pickedSize = React.useMemo(
    () => instVoices.filter(v => instPicked[v.rel]).reduce((s, v) => s + v.size, 0),
    [instVoices, instPicked]
  );

  const switchVoice = async (id) => {
    setVoiceBusy(id); setTtsMsg('');
    try {
      const r = await fetch('/api/tts/set_voice', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ voice_id: id })
      }).then(r => r.json());
      setTtsMsg(r.ok ? `已切换音色: ${id}` : (r.msg || r.message || '切换失败'));
      if (r.ok) setSettings({ ...settings, ttsVoiceId: id });
    } catch (e) { setTtsMsg('切换失败: ' + e.message); }
    setVoiceBusy('');
  };

  // ================= Qwen3-TTS 控制 =================
  const fetchQwenStatus = React.useCallback(async () => {
    try {
      const s = await fetch('/api/tts/qwen/status').then(r => r.json());
      setQwenStatus(s);
      return s;
    } catch { setQwenStatus({ ok: false, running: false }); return null; }
  }, []);

  const fetchQwenVoices = React.useCallback(async () => {
    try {
      const d = await fetch('/api/tts/qwen/voices').then(r => r.json());
      setQwenVoices(Array.isArray(d.voices) ? d.voices : []);
    } catch { setQwenVoices([]); }
  }, []);

  const fetchEmotions = React.useCallback(async () => {
    try {
      const d = await fetch('/api/tts/qwen/emotions').then(r => r.json());
      setEmotions(Array.isArray(d.emotions) ? d.emotions : []);
    } catch { setEmotions([]); }
  }, []);

  React.useEffect(() => {
    fetchQwenStatus().then(s => { if (s?.running) { fetchQwenVoices(); fetchEmotions(); } });
  }, [fetchQwenStatus, fetchQwenVoices, fetchEmotions]);

  const startQwen = async () => {
    setQwenBusy(true); setQwenStarting(true); setQwenMsg('正在启动，首次需下载/加载模型（可能数分钟）…');
    try {
      const r = await fetch('/api/tts/qwen/start', { method: 'POST' }).then(r => r.json());
      if (!r.ok) {
        setQwenMsg(r.msg || '启动失败');
        if (r.need_model) { await fetchQwenModelStatus(); setShowModelDlg(true); }
        setQwenBusy(false); setQwenStarting(false); return;
      }
      setQwenBusy(false);
      let i = 0;
      qwenPollRef.current = setInterval(async () => {
        i++;
        const s = await fetchQwenStatus();
        if (s?.ready) {
          clearInterval(qwenPollRef.current); qwenPollRef.current = null;
          setQwenMsg('Qwen3-TTS 已就绪'); setQwenStarting(false); await fetchQwenVoices(); await fetchEmotions();
        } else if (i >= 300) {
          clearInterval(qwenPollRef.current); qwenPollRef.current = null;
          setQwenMsg('启动超时，请查看 Qwen3-TTS 日志'); setQwenStarting(false);
        }
      }, 2000);
    } catch (e) { setQwenMsg('启动失败: ' + e.message); setQwenBusy(false); setQwenStarting(false); }
  };

  const stopQwen = async () => {
    if (qwenPollRef.current) { clearInterval(qwenPollRef.current); qwenPollRef.current = null; }
    setQwenStarting(false);
    setQwenBusy(true); setQwenMsg('正在停止…');
    try {
      const r = await fetch('/api/tts/qwen/stop', { method: 'POST' }).then(r => r.json());
      setQwenMsg(r.msg || '');
      await fetchQwenStatus();
    } catch (e) { setQwenMsg('停止失败: ' + e.message); }
    setQwenBusy(false);
  };

  // ================= Qwen3-TTS 模型下载（独立） =================
  const fetchQwenModelStatus = React.useCallback(async () => {
    try {
      const d = await fetch('/api/tts/qwen/model/status').then(r => r.json());
      setQwenModel(d);
      return d;
    } catch { return null; }
  }, []);

  const fetchQwenModelDl = React.useCallback(async () => {
    try {
      const d = await fetch('/api/tts/qwen/download_model/status').then(r => r.json());
      setQwenModelDl(d);
      return d;
    } catch { return null; }
  }, []);

  React.useEffect(() => { fetchQwenModelStatus(); }, [fetchQwenModelStatus]);

  const startModelDownload = async () => {
    setShowModelDlg(false);
    setQwenModelDl(prev => ({ ...(prev || {}), running: true, done: false, step: '开始下载模型…', percent: 0 }));
    try {
      const r = await fetch('/api/tts/qwen/download_model', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ hf_endpoint: modelHfEndpoint || '', source: modelSource || 'auto' })
      }).then(r => r.json());
      if (!r.ok) { setQwenModelDl(prev => ({ ...(prev || {}), running: false, error: r.msg })); return; }
      if (r.already) { setQwenModelDl(prev => ({ ...(prev || {}), running: false, done: true, ok: true, step: '模型已就绪' })); return; }
      const timer = setInterval(async () => {
        const d = await fetchQwenModelDl();
        if (d && d.done) {
          clearInterval(timer);
          await fetchQwenModelStatus();
        }
      }, 2000);
    } catch (e) {
      setQwenModelDl(prev => ({ ...(prev || {}), running: false, error: '下载启动失败: ' + e.message }));
    }
  };

  const switchQwenVoice = async (id) => {
    setQwenVoiceBusy(id); setQwenMsg('');
    try {
      const r = await fetch('/api/tts/qwen/set_voice', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ voice_id: id })
      }).then(r => r.json());
      setQwenMsg(r.ok ? `已切换音色: ${id}` : (r.msg || r.message || '切换失败'));
      if (r.ok) setSettings({ ...settings, ttsQwenVoiceId: id });
    } catch (e) { setQwenMsg('切换失败: ' + e.message); }
    setQwenVoiceBusy('');
  };

  // ================= Qwen3 音色保存/删除 =================
  const saveQwenVoice = async () => {
    const vid = (qwenVoiceForm.id || '').trim();
    if (!vid) { setQwenMsg('音色名不能为空'); return; }
    if (!qwenVoiceFile && !qwenVoiceForm.text) { setQwenMsg('请提供参考音频文件或参考音频文本'); return; }
    setQwenVoiceSaving(true); setQwenMsg('');
    try {
      const fd = new FormData();
      fd.append('voice_id', vid);
      fd.append('ref_text', qwenVoiceForm.text || '');
      if (qwenVoiceFile) fd.append('ref_audio', qwenVoiceFile);
      const r = await fetch('/api/tts/qwen/voice/save', { method: 'POST', body: fd }).then(r => r.json());
      setQwenMsg(r.ok ? `音色 ${vid} 已保存` : (r.message || r.msg || '保存失败'));
      if (r.ok) { setQwenVoiceForm({ id: '', text: '' }); setQwenVoiceFile(null); await fetchQwenVoices(); }
    } catch (e) { setQwenMsg('保存失败: ' + e.message); }
    setQwenVoiceSaving(false);
  };

  const deleteQwenVoice = async (id) => {
    if (!window.confirm(`确定删除音色 ${id} 吗？将删除其参考音频与文字稿。`)) return;
    try {
      const r = await fetch(`/api/tts/qwen/voice/${encodeURIComponent(id)}`, { method: 'DELETE' }).then(r => r.json());
      setQwenMsg(r.ok ? `已删除 ${id}` : (r.message || r.msg || '删除失败'));
      await fetchQwenVoices();
    } catch (e) { setQwenMsg('删除失败: ' + e.message); }
  };

  // 编辑音色：把已有音色的信息填回表单，修改后保存会覆盖更新
  const editQwenVoice = (v) => {
    setQwenVoiceForm({ id: v.id, text: v.ref_txt_content || '' });
    setQwenVoiceFile(null);
    setQwenMsg(`已在编辑音色「${v.id}」，可重新上传参考音频或修改文字稿后保存。`);
    // 滚动到表单
    try { document.getElementById('qwen-voice-add-form')?.scrollIntoView({ behavior: 'smooth', block: 'center' }); } catch (e) {}
  };

  // ================= GPT-SoVITS 模型快速添加 =================
  const addSovitsModel = async () => {
    const f = sovitsModelForm;
    if (!f.name) { setTtsMsg('角色名不能为空'); return; }
    setSovitsModelSaving(true); setTtsMsg('');
    try {
      const r = await fetch('/api/tts/sovits/model/add', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(f)
      }).then(r => r.json());
      setTtsMsg(r.msg || (r.ok ? '已添加' : '添加失败'));
      if (r.ok) { setSovitsModelForm({ name: '', version: 'v2ProPlus', ckpt: '', pth: '', ref_audio: '', ref_text: '' }); await fetchVoices(); }
    } catch (e) { setTtsMsg('添加失败: ' + e.message); }
    setSovitsModelSaving(false);
  };

  // ================= Qwen3-TTS 一键安装 =================
  const fetchQwenInstall = React.useCallback(async () => {
    try {
      const d = await fetch('/api/tts/qwen/install/status').then(r => r.json());
      setQwenInstall(d);
      return d;
    } catch { return null; }
  }, []);

  React.useEffect(() => {
    fetchQwenInstall();
  }, [fetchQwenInstall]);

  const startQwenInstall = async () => {
    setQwenInstall(prev => ({ ...(prev || {}), running: true, done: false, step: '开始安装…', percent: 0, log: [] }));
    try {
      const r = await fetch('/api/tts/qwen/install', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          pip_index: qwenInstallPipIndex || '',
          hf_endpoint: qwenInstallHf || '',
          with_model: qwenInstallWithModel,
          torch_variant: qwenInstallTorchVariant || '',
        })
      }).then(r => r.json());
      if (!r.ok) { setQwenInstall(prev => ({ ...(prev || {}), running: false, error: r.msg })); return; }
      // 轮询进度直到完成
      const timer = setInterval(async () => {
        const d = await fetchQwenInstall();
        if (d && d.done) {
          clearInterval(timer);
          await fetchQwenStatus();
          if (d.ok) setQwenMsg('安装完成，可以启动 Qwen3-TTS 了');
        }
      }, 1500);
    } catch (e) {
      setQwenInstall(prev => ({ ...(prev || {}), running: false, error: '安装启动失败: ' + e.message }));
    }
  };

  // ================= torch 版本管理 + 检查更新 =================
  const fetchTorchInfo = React.useCallback(async () => {
    try {
      const d = await fetch('/api/tts/qwen/torch/info').then(r => r.json());
      setTorchInfo(d);
      return d;
    } catch { return null; }
  }, []);

  const fetchTorchOp = React.useCallback(async () => {
    try {
      const d = await fetch('/api/tts/qwen/torch/status').then(r => r.json());
      setTorchOp(d);
      return d;
    } catch { return null; }
  }, []);

  React.useEffect(() => { fetchTorchInfo(); }, [fetchTorchInfo]);

  const switchTorch = async (variant) => {
    setShowTorchDlg(false);
    setTorchOp(prev => ({ ...(prev || {}), running: true, done: false, step: '开始切换 torch…', percent: 0 }));
    try {
      const r = await fetch('/api/tts/qwen/torch/install', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ variant, mirror: torchMirror || 'sjtug' })
      }).then(r => r.json());
      if (!r.ok) { setTorchOp(prev => ({ ...(prev || {}), running: false, error: r.msg })); return; }
      const timer = setInterval(async () => {
        const d = await fetchTorchOp();
        if (d && d.done) {
          clearInterval(timer);
          await fetchTorchInfo();
        }
      }, 2000);
    } catch (e) {
      setTorchOp(prev => ({ ...(prev || {}), running: false, error: '切换失败: ' + e.message }));
    }
  };

  // ================= 硬件检测 / 模型管理 / 镜像 / 文档 =================
  const fetchHardware = React.useCallback(async () => {
    try {
      const d = await fetch('/api/tts/qwen/hardware').then(r => r.json());
      setHardware(d);
      return d;
    } catch { return null; }
  }, []);

  const fetchQwenModels = React.useCallback(async () => {
    try {
      const d = await fetch('/api/tts/qwen/models').then(r => r.json());
      setQwenModels(d);
      return d;
    } catch { return null; }
  }, []);

  const fetchTorchMirrors = React.useCallback(async () => {
    try {
      const d = await fetch('/api/tts/qwen/torch/mirrors').then(r => r.json());
      setTorchMirrors(Array.isArray(d.mirrors) ? d.mirrors : []);
    } catch { setTorchMirrors([]); }
  }, []);

  React.useEffect(() => { fetchHardware(); fetchQwenModels(); fetchTorchMirrors(); }, [fetchHardware, fetchQwenModels, fetchTorchMirrors]);

  const switchQwenModel = async (model) => {
    if (!window.confirm(`确定切换到模型 ${model} 吗？切换后需重启 Qwen3-TTS 才生效。`)) return;
    try {
      const r = await fetch('/api/tts/qwen/model/switch', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model })
      }).then(r => r.json());
      if (r.ok) { setQwenMsg(`已切换到 ${model}，重启 Qwen3-TTS 后生效`); await fetchQwenModels(); }
      else setQwenMsg(r.msg || '切换失败');
    } catch (e) { setQwenMsg('切换失败: ' + e.message); }
  };

  const uninstallQwenModel = async (model) => {
    if (!window.confirm(`确定卸载模型 ${model} 吗？将删除本地缓存（约数 GB），需重新下载才能使用。`)) return;
    try {
      const r = await fetch('/api/tts/qwen/model/uninstall', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model })
      }).then(r => r.json());
      setQwenMsg(r.ok ? `已卸载 ${model}` : (r.msg || '卸载失败'));
      await fetchQwenModels();
    } catch (e) { setQwenMsg('卸载失败: ' + e.message); }
  };

  const uninstallTorch = async () => {
    if (!window.confirm('确定要卸载 torch 吗？卸载后 Qwen3-TTS 将无法合成语音，需重新安装 torch 才能使用。')) return;
    setTorchOp(prev => ({ ...(prev || {}), running: true, done: false, step: '卸载 torch…', percent: 0 }));
    try {
      const r = await fetch('/api/tts/qwen/torch/uninstall', { method: 'POST' }).then(r => r.json());
      if (!r.ok) { setTorchOp(prev => ({ ...(prev || {}), running: false, error: r.msg })); return; }
      const timer = setInterval(async () => {
        const d = await fetchTorchOp();
        if (d && d.done) {
          clearInterval(timer);
          await fetchTorchInfo();
        }
      }, 2000);
    } catch (e) {
      setTorchOp(prev => ({ ...(prev || {}), running: false, error: '卸载失败: ' + e.message }));
    }
  };

  const checkUpdates = async () => {
    setCheckingUpdate(true); setUpdates(null);
    try {
      const d = await fetch('/api/tts/qwen/check_updates', { method: 'POST' }).then(r => r.json());
      setUpdates(d);
    } catch (e) { setUpdates({ ok: false, msg: '检查失败: ' + e.message, items: [] }); }
    setCheckingUpdate(false);
  };

  const updatePackage = async (pkg) => {
    if (!window.confirm(`确定要升级 ${pkg} 到最新版吗？`)) return;
    setTorchOp(prev => ({ ...(prev || {}), running: true, done: false, step: `升级 ${pkg}…`, percent: 0 }));
    try {
      const r = await fetch('/api/tts/qwen/update_package', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ package: pkg })
      }).then(r => r.json());
      if (!r.ok) { setTorchOp(prev => ({ ...(prev || {}), running: false, error: r.msg })); return; }
      const timer = setInterval(async () => {
        const d = await fetch('/api/tts/qwen/update/status').then(rr => rr.json());
        if (d && d.done) { clearInterval(timer); await checkUpdates(); }
      }, 2000);
    } catch (e) {
      setTorchOp(prev => ({ ...(prev || {}), running: false, error: '升级失败: ' + e.message }));
    }
  };

  // 强制终止所有正在进行的下载/安装/加载进程（停止按钮）
  const cancelTask = async (label) => {
    try {
      const r = await fetch('/api/tts/qwen/cancel', { method: 'POST' }).then(r => r.json());
      if (r.ok) { setQwenMsg(`已发送停止指令：${label || ''}`); }
      // 刷新各类进度，让其回到非 running 状态
      await Promise.all([fetchQwenInstall(), fetchQwenModelDl(), fetchTorchOp()]);
    } catch (e) { setQwenMsg('停止失败: ' + e.message); }
  };

  return (
    <div className="space-y-8 animate-fade-in">
      {/* 主界面音乐组件 */}
      <SettingSectionTitle title="主界面音乐组件设定" />
      <div className="bg-white/60 p-6 rounded-xl border border-[#e6d5b8] shadow-sm">
        <SettingToggle label="在主界面显示音乐播放器 (可拖拽)" value={settings.showTitleBgmPlayer} onChange={v => setSettings({...settings, showTitleBgmPlayer: v})} />
        <p className="text-xs text-[#7a6b5d] mt-2">开启后在主标题界面左下角显示半透明悬浮播放器。</p>
      </div>

      {/* 音量与播放控制 */}
      <SettingSectionTitle title="音量与播放控制" />
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 bg-white/60 p-6 rounded-xl border border-[#e6d5b8] shadow-sm">
        <SettingSlider label="背景音乐音量 (BGM)" value={settings.bgmVolume} min={0} max={1} step={0.05} suffix="" onChange={v => setSettings({...settings, bgmVolume: v})} />
        <SettingSlider label="语音合成音量 (TTS)" value={settings.ttsVolume} min={0} max={1} step={0.05} suffix="" onChange={v => setSettings({...settings, ttsVolume: v})} />
        <SettingSlider label="语音播放倍速" value={settings.ttsPlaybackRate} min={0.5} max={2.0} step={0.1} suffix="x" onChange={v => setSettings({...settings, ttsPlaybackRate: v})} />
      </div>

      {/* BGM 管理 */}
      <div className="bg-white/60 p-6 rounded-xl border border-[#e6d5b8] shadow-sm">
        <label className="block text-sm font-bold text-[#ba3f42] mb-3">导入本地背景音乐 (支持多首)</label>
        <div className="flex gap-4 items-center mb-4">
          <input type="file" accept="audio/*" multiple onChange={handleBgmUpload} className="block w-full text-sm text-[#7a6b5d] file:mr-4 file:py-2 file:px-4 file:rounded-full file:border-0 file:text-sm file:font-bold file:bg-[#8fbf8f] file:text-white hover:file:bg-[#7ebd7e] cursor-pointer"/>
          <select value={settings.bgmMode} onChange={e => setSettings({...settings, bgmMode: e.target.value})} className="bg-white border border-[#d9c5b2] text-[#4a4036] font-bold text-sm rounded-md px-4 py-2 outline-none shadow-inner">
            <option value="sequential">顺序播放</option><option value="random">随机播放</option><option value="loop">单曲循环</option>
          </select>
        </div>
        {bgmList.length > 0 && (
          <div className="max-h-40 overflow-y-auto bg-white rounded-lg p-2 border border-[#e6d5b8] space-y-1 mb-4">
            {bgmList.map((bgm, idx) => (
              <div key={bgm.id} className={`flex justify-between items-center px-4 py-2 rounded text-sm group transition-colors ${currentBgmIndex === idx ? 'bg-[#8fbf8f]/20 font-bold text-[#4a4036]' : 'hover:bg-black/5 text-[#7a6b5d]'}`}>
                <span className="truncate pr-4 flex-1 cursor-pointer" onClick={() => { setCurrentBgmIndex(idx); if(!isBgmPlaying) toggleBgm(); }}>{currentBgmIndex === idx && isBgmPlaying ? '🎶 ' : ''}{bgm.name}</span>
                <button onClick={() => removeBgm(bgm.id)} className="opacity-0 group-hover:opacity-100 text-red-500 hover:text-red-600 px-2 shrink-0"><Trash2 size={16}/></button>
              </div>
            ))}
          </div>
        )}
        <SettingToggle label="切歌时显示歌曲名称" value={settings.enableBgmToast} onChange={v => setSettings({...settings, enableBgmToast: v})} />
      </div>

      {/* TTS 语音合成 */}
      <SettingSectionTitle title="语音合成 (TTS) 接口" />
      <div className="bg-white/60 p-6 rounded-xl border border-[#e6d5b8] shadow-sm space-y-6">
        <SettingToggle label="开启全局 TTS 自动朗读" value={settings.ttsEnabled} onChange={v => setSettings({...settings, ttsEnabled: v})} />
        <div className={`grid grid-cols-1 md:grid-cols-3 gap-6 transition-opacity ${!settings.ttsEnabled && 'opacity-50 pointer-events-none'}`}>
          <div>
            <label className="block text-sm font-bold text-[#ba3f42] mb-2">发音语言</label>
            <select value={settings.ttsLanguage} onChange={e => setSettings({...settings, ttsLanguage: e.target.value})} className="w-full bg-white border border-[#d9c5b2] text-[#4a4036] font-bold rounded-md px-3 py-2 outline-none shadow-inner">
              <option value="zh">中文</option><option value="ja">日文</option><option value="en">英文</option><option value="ko">韩文</option>
            </select>
          </div>
          <div className="md:col-span-2">
            <label className="block text-sm font-bold text-[#ba3f42] mb-2">API URL 模板</label>
            <input type="text" value={settings.ttsUrlTemplate} onChange={e => setSettings({...settings, ttsUrlTemplate: e.target.value})} className="w-full bg-white border border-[#d9c5b2] text-[#4a4036] rounded-md px-3 py-2 text-sm outline-none shadow-inner" />
            <div className="bg-[#fdfaf5] p-3 mt-2 rounded border border-[#e6d5b8]">
              <p className="text-[11px] text-[#7a6b5d] font-bold mb-1"><AlertCircle size={12} className="inline mr-1 text-[#ba3f42]"/> 模板示例：</p>
              <code className="text-[10px] text-blue-600 break-all select-all block bg-white p-1.5 rounded border border-[#d9c5b2]">http://127.0.0.1:9880/tts?text={'{text}'}&text_lang={'{lang}'}&ref_audio_path={'{ref_audio}'}&prompt_text={'{ref_text}'}&prompt_lang={'{ref_lang}'}</code>
            </div>
          </div>
          <div className="md:col-span-3 border-t border-dashed border-[#e6d5b8] pt-4">
            <SettingSlider label="流式分句停顿时间" value={settings.ttsSentencePause} min={0} max={3000} step={10} suffix="ms" onChange={v => setSettings({...settings, ttsSentencePause: v})} />
          </div>
          <div className="md:col-span-3">
            <SettingToggle label="🚀 极速短标点切句预加载" value={settings.ttsFastMode} onChange={v => setSettings({...settings, ttsFastMode: v})} />
            <p className="text-xs text-[#7a6b5d] mt-2 leading-relaxed bg-[#fdfaf5] p-3 rounded-lg border border-[#e6d5b8]"><strong className="text-emerald-600">GPT-SoVITS 优化：</strong>开启后遇到逗号就预加载下一句，消除排队延迟。</p>
          </div>
          <div className="md:col-span-3 border-t border-dashed border-[#e6d5b8] pt-6">
            <div className="flex flex-col md:flex-row justify-between items-start md:items-center mb-4 gap-4">
              <h4 className="text-sm font-bold text-[#4a4036]">参考音频配置 (克隆/指定音色必填)</h4>
              <div className="flex items-center gap-4">
                {/* 引擎切换开关：GPT-SoVITS | Qwen3-TTS 无缝切换 */}
                <div className="flex items-center gap-2">
                  <span className="text-xs font-bold text-[#7a6b5d]">配音引擎</span>
                  <select value={settings.ttsEngine || 'sovits'} onChange={e => setSettings({ ...settings, ttsEngine: e.target.value })} className="bg-white border border-[#d9c5b2] text-[#4a4036] font-bold rounded-md px-3 py-1.5 text-xs outline-none shadow-inner">
                    <option value="sovits">GPT-SoVITS（旧）</option>
                    <option value="qwen">Qwen3-TTS（新）</option>
                  </select>
                </div>
                <SettingToggle label="🎙️ 内置配音" value={settings.ttsBuiltIn} onChange={v => setSettings({...settings, ttsBuiltIn: v})} />
              </div>
            </div>

            {/* 内置配音控制台：按引擎切换显示不同控制台 */}
            {settings.ttsBuiltIn && settings.ttsEngine === 'sovits' && (
              <div className="mb-5 bg-[#fdfaf5] p-5 rounded-xl border border-[#e6d5b8] shadow-inner space-y-4">
                <div className="flex items-center justify-between gap-3 flex-wrap">
                  <div className="flex items-center gap-2 min-w-0">
                    <Mic2 size={16} className="text-[#4fa0d8] shrink-0" />
                    <span className="text-sm font-black text-[#4a4036]">内置配音服务 (GPT-SoVITS)</span>
                    <button onClick={() => setShowDoc('sovits')} title="查看配置文档"
                      className="px-2 py-0.5 text-[10px] font-bold text-[#4fa0d8] border border-[#4fa0d8]/40 rounded-full hover:bg-[#4fa0d8]/10">📘 文档</button>
                    {ttsStatus === null ? (
                      <span className="text-xs text-[#a89578]">检测中…</span>
                    ) : ttsStatus.running ? (
                      <span className="text-xs font-bold text-emerald-600 flex items-center gap-1">
                        <CheckCircle size={12} /> 运行中
                        {ttsStatus.health?.version && ` · ${ttsStatus.health.version}`}
                        {ttsStatus.health?.device && ` · ${ttsStatus.health.device}`}
                      </span>
                    ) : (
                      <span className="text-xs font-bold text-[#a89578] flex items-center gap-1"><XCircle size={12} /> 未运行</span>
                    )}
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    {ttsStatus && !ttsStatus.installed ? null : (ttsStarting || ttsStatus?.running) ? (
                      <button onClick={stopTts} disabled={ttsBusy}
                        className="flex items-center gap-1.5 px-4 py-1.5 bg-[#ba3f42] hover:bg-[#a03538] text-white text-xs font-bold rounded-full transition-colors disabled:opacity-50">
                        {ttsBusy ? <Loader2 size={13} className="animate-spin" /> : <Square size={13} />} {ttsStarting ? '取消启动' : '停止'}
                      </button>
                    ) : (
                      <button onClick={startTts} disabled={ttsBusy}
                        className="flex items-center gap-1.5 px-4 py-1.5 bg-[#8fbf8f] hover:bg-[#7ebd7e] text-white text-xs font-bold rounded-full transition-colors disabled:opacity-50">
                        {ttsBusy ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />} 启动
                      </button>
                    )}
                    <button onClick={() => { fetchTtsStatus(); fetchVoices(); }} disabled={ttsBusy || ttsStarting}
                      className="flex items-center gap-1.5 px-3 py-1.5 bg-[#4fa0d8] hover:bg-[#5db4f0] text-white text-xs font-bold rounded-full transition-colors disabled:opacity-50">
                      <RefreshCw size={13} /> 刷新
                    </button>
                  </div>
                </div>

                {ttsMsg && <p className="text-xs font-bold text-[#4fa0d8]">{ttsMsg}</p>}

                {/* 未安装：引导从本机 GPT-SoVITS 一键导入（分发包不含大文件） */}
                {ttsStatus && !ttsStatus.installed && (
                  <div className="bg-white rounded-lg border border-[#e6d5b8] p-4 space-y-3">
                    <p className="text-xs text-[#7a6b5d] leading-relaxed">
                      内置配音尚未安装。为控制分发体积，推理代码与模型不随程序附带，
                      可从本机已安装的 <b>GPT-SoVITS</b> 一键导入（仅复制文件，不修改原目录）。
                    </p>

                    {instProg?.running || instProg?.done ? (
                      <div>
                        <div className="flex justify-between text-xs font-bold text-[#4a4036] mb-1">
                          <span>{instProg.step}</span><span>{instProg.percent}%</span>
                        </div>
                        <div className="h-2 bg-[#e8decb] rounded-full overflow-hidden">
                          <div className="h-full bg-[#8fbf8f] transition-all" style={{ width: `${instProg.percent}%` }} />
                        </div>
                        {instProg.error && <p className="text-xs text-[#ba3f42] mt-2">{instProg.error}</p>}
                      </div>
                    ) : instSources === null ? (
                      <button onClick={() => scanSources()} disabled={instScanning}
                        className="flex items-center gap-1.5 px-4 py-1.5 bg-[#4fa0d8] hover:bg-[#5db4f0] text-white text-xs font-bold rounded-full disabled:opacity-50">
                        {instScanning ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />} 扫描本机 GPT-SoVITS
                      </button>
                    ) : instSources.length === 0 ? (
                      <div className="space-y-2">
                        <p className="text-xs text-[#ba3f42]">未找到 GPT-SoVITS 安装，请手动指定其根目录：</p>
                        <div className="flex gap-2">
                          <input type="text" value={instPath} onChange={e => setInstPath(e.target.value)}
                            placeholder="如: D:\GPT-SoVITS\GPT-SoVITS-v2pro-xxxxxxxx"
                            className="flex-1 bg-white border border-[#d9c5b2] rounded-md px-3 py-1.5 text-xs outline-none" />
                          <button onClick={() => scanSources(instPath)} disabled={!instPath || instScanning}
                            className="px-3 py-1.5 bg-[#4fa0d8] text-white text-xs font-bold rounded-full disabled:opacity-50">检测</button>
                        </div>
                        <p className="text-[11px] text-[#a89578]">
                          没有的话，可前往 GPT-SoVITS 官方仓库下载整合包，解压后指定该目录即可。
                        </p>
                      </div>
                    ) : (
                      <div className="space-y-3">
                        <div>
                          <label className="block text-xs font-bold text-[#7a6b5d] mb-1">来源目录</label>
                          <select value={instPath} onChange={e => { setInstPath(e.target.value); loadInstVoices(e.target.value); }}
                            className="w-full bg-white border border-[#d9c5b2] rounded-md px-3 py-1.5 text-xs outline-none">
                            {instSources.map(s => (
                              <option key={s.path} value={s.path}>{s.path}{s.has_runtime ? ' (含运行时)' : ' (无运行时)'}</option>
                            ))}
                          </select>
                        </div>

                        {instVoices.length > 0 && (
                          <div>
                            <div className="flex items-center justify-between mb-1">
                              <label className="text-xs font-bold text-[#7a6b5d]">选择要导入的音色</label>
                              <span className="text-[11px] text-[#a89578]">
                                已选 {Object.values(instPicked).filter(Boolean).length} 个 · 约 {(pickedSize / 1024 / 1024 / 1024).toFixed(2)} GB
                              </span>
                            </div>
                            <div className="max-h-40 overflow-y-auto bg-[#fdfaf5] rounded border border-[#e6d5b8] p-2 space-y-1">
                              {instVoices.map(v => (
                                <label key={v.rel} className="flex items-center gap-2 text-[11px] cursor-pointer hover:bg-white/60 px-1 rounded">
                                  <input type="checkbox" checked={!!instPicked[v.rel]}
                                    onChange={e => setInstPicked({ ...instPicked, [v.rel]: e.target.checked })}
                                    className="accent-[#4fa0d8]" />
                                  <span className={`font-bold ${v.kind === 'gpt' ? 'text-[#ba3f42]' : 'text-[#4fa0d8]'}`}>{v.kind}</span>
                                  <span className="flex-1 truncate text-[#4a4036]">{v.file}</span>
                                  <span className="text-[#a89578]">{(v.size / 1024 / 1024).toFixed(0)}MB</span>
                                </label>
                              ))}
                            </div>
                            <p className="text-[11px] text-[#a89578] mt-1">
                              已默认勾选每个角色轮次最高的一组。GPT 与 SoVITS 需成对导入才能使用。
                            </p>
                          </div>
                        )}

                        <button onClick={startInstall}
                          className="flex items-center gap-1.5 px-4 py-1.5 bg-[#8fbf8f] hover:bg-[#7ebd7e] text-white text-xs font-bold rounded-full">
                          <Play size={13} /> 开始导入
                        </button>
                      </div>
                    )}
                  </div>
                )}

                {ttsStatus && !ttsStatus.runtime_ok && (
                  <p className="text-xs text-[#ba3f42] leading-relaxed">
                    未找到 Python 运行时：<code className="break-all">{ttsStatus.runtime}</code><br />
                    内置配音共享原 GPT-SoVITS 安装目录的 runtime。若路径不同，请设置环境变量 <b>GWC_SOVITS_RUNTIME</b> 指向 runtime\python.exe。
                  </p>
                )}

                {/* 音色管理（快速添加 + 列表 + 刷新） */}
                {ttsStatus?.running && (
                  <div className="space-y-3">
                    <div className="flex items-center justify-between mb-1">
                      <label className="text-xs font-bold text-[#7a6b5d]">音色列表</label>
                      <button onClick={fetchVoices} className="flex items-center gap-1 px-2 py-1 bg-[#4fa0d8] hover:bg-[#5db4f0] text-white text-[10px] font-bold rounded-full">
                        <RefreshCw size={11} /> 刷新
                      </button>
                    </div>

                    {/* 快速添加模型 */}
                    <div className="bg-white rounded-lg border border-[#e6d5b8] p-3 space-y-2">
                      <label className="text-[11px] font-bold text-[#4a4036]">➕ 快速添加模型（复制 ckpt/pth/参考音频到 tts 目录）</label>
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                        <input type="text" value={sovitsModelForm.name} onChange={e => setSovitsModelForm({ ...sovitsModelForm, name: e.target.value })}
                          placeholder="角色名（如 ATRI）"
                          className="bg-white border border-[#d9c5b2] rounded-md px-2 py-1.5 text-[11px] outline-none" />
                        <select value={sovitsModelForm.version} onChange={e => setSovitsModelForm({ ...sovitsModelForm, version: e.target.value })}
                          className="bg-white border border-[#d9c5b2] rounded-md px-2 py-1.5 text-[11px] outline-none">
                          <option value="v2ProPlus">推理版本 v2ProPlus</option>
                          <option value="v2Pro">v2Pro</option>
                          <option value="v4">v4</option>
                        </select>
                        <input type="text" value={sovitsModelForm.ckpt} onChange={e => setSovitsModelForm({ ...sovitsModelForm, ckpt: e.target.value })}
                          placeholder="ckpt 文件路径（GPT 权重）"
                          className="bg-white border border-[#d9c5b2] rounded-md px-2 py-1.5 text-[11px] outline-none" />
                        <input type="text" value={sovitsModelForm.pth} onChange={e => setSovitsModelForm({ ...sovitsModelForm, pth: e.target.value })}
                          placeholder="pth 文件路径（SoVITS 权重）"
                          className="bg-white border border-[#d9c5b2] rounded-md px-2 py-1.5 text-[11px] outline-none" />
                        <input type="text" value={sovitsModelForm.ref_audio} onChange={e => setSovitsModelForm({ ...sovitsModelForm, ref_audio: e.target.value })}
                          placeholder="参考音频路径（如 D:\audio\ref.wav）"
                          className="bg-white border border-[#d9c5b2] rounded-md px-2 py-1.5 text-[11px] outline-none" />
                        <input type="text" value={sovitsModelForm.ref_text} onChange={e => setSovitsModelForm({ ...sovitsModelForm, ref_text: e.target.value })}
                          placeholder="参考音频文本"
                          className="bg-white border border-[#d9c5b2] rounded-md px-2 py-1.5 text-[11px] outline-none" />
                      </div>
                      <button onClick={addSovitsModel} disabled={sovitsModelSaving}
                        className="flex items-center gap-1 px-3 py-1.5 bg-[#8fbf8f] hover:bg-[#7ebd7e] text-white text-[11px] font-bold rounded-full disabled:opacity-50">
                        {sovitsModelSaving ? <Loader2 size={11} className="animate-spin" /> : null} 添加模型
                      </button>
                    </div>

                    {/* 音色列表 */}
                    {ttsVoices.length === 0 ? (
                      <p className="text-xs text-[#a89578]">未发现音色。用上方「快速添加模型」复制 ckpt/pth 后刷新，或手动放入 tts/models/gpt 与 tts/models/sovits。</p>
                    ) : (
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                        {ttsVoices.map(v => (
                          <button key={v.id} onClick={() => v.usable && switchVoice(v.id)}
                            disabled={!v.usable || !!voiceBusy}
                            title={v.usable ? `${v.gpt} + ${v.sovits}` : '缺少 GPT 或 SoVITS 权重，无法使用'}
                            className={`text-left px-3 py-2 rounded-lg text-xs font-bold border transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${
                              settings.ttsVoiceId === v.id
                                ? 'bg-[#4fa0d8]/10 border-[#4fa0d8] text-[#4fa0d8]'
                                : 'bg-white border-[#e6d5b8] text-[#4a4036] hover:border-[#4fa0d8]'
                            }`}>
                            <span className="font-black">{v.name}</span>
                            {voiceBusy === v.id && <Loader2 size={11} className="inline ml-2 animate-spin" />}
                            {settings.ttsVoiceId === v.id && voiceBusy !== v.id && <CheckCircle size={11} className="inline ml-2" />}
                            {!v.usable && <span className="ml-2 font-normal text-[#a89578]">权重不全</span>}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                <p className="text-[11px] text-[#7a6b5d] leading-relaxed border-t border-dashed border-[#e6d5b8] pt-3">
                  内置配音随项目一起提供，无需另外部署。推理代码与音色位于 <code>tts/</code> 目录，
                  Python 运行时共享自原 GPT-SoVITS 安装（以节省约 6.6GB 空间）。
                  服务地址为 <code>127.0.0.1:9880</code>，与上方 API URL 模板一致。
                </p>
              </div>
            )}

            {/* Qwen3-TTS 控制台：零训练克隆 + instruct 情绪控制 */}
            {settings.ttsBuiltIn && settings.ttsEngine === 'qwen' && (
              <div className="mb-5 bg-[#fdfaf5] p-5 rounded-xl border border-[#e6d5b8] shadow-inner space-y-4">
                <div className="flex items-center justify-between gap-3 flex-wrap">
                  <div className="flex items-center gap-2 min-w-0">
                    <Mic2 size={16} className="text-[#8fbf8f] shrink-0" />
                    <span className="text-sm font-black text-[#4a4036]">内置配音服务 (Qwen3-TTS)</span>
                    <button onClick={() => setShowDoc('qwen')} title="查看配置文档"
                      className="px-2 py-0.5 text-[10px] font-bold text-[#4fa0d8] border border-[#4fa0d8]/40 rounded-full hover:bg-[#4fa0d8]/10">📘 文档</button>
                    {qwenStatus === null ? (
                      <span className="text-xs text-[#a89578]">检测中…</span>
                    ) : qwenStatus.running ? (
                      <span className="text-xs font-bold text-emerald-600 flex items-center gap-1">
                        {qwenStatus.loading ? <><Loader2 size={12} className="animate-spin" /> 加载中…</> : <><CheckCircle size={12} /> 运行中</>}
                        {qwenStatus.health?.model && ` · ${qwenStatus.health.model}`}
                      </span>
                    ) : (
                      <span className="text-xs font-bold text-[#a89578] flex items-center gap-1"><XCircle size={12} /> 未运行</span>
                    )}
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    {qwenStatus && !qwenStatus.installed ? null : (qwenStarting || qwenStatus?.running) ? (
                      <button onClick={stopQwen} disabled={qwenBusy}
                        className="flex items-center gap-1.5 px-4 py-1.5 bg-[#ba3f42] hover:bg-[#a03538] text-white text-xs font-bold rounded-full transition-colors disabled:opacity-50">
                        {qwenBusy ? <Loader2 size={13} className="animate-spin" /> : <Square size={13} />} {qwenStarting ? '取消启动' : '停止'}
                      </button>
                    ) : (
                      <button onClick={startQwen} disabled={qwenBusy || (qwenStatus && !qwenStatus.env_ready)}
                        title={qwenStatus && !qwenStatus.env_ready ? '请先安装独立环境' : ''}
                        className="flex items-center gap-1.5 px-4 py-1.5 bg-[#8fbf8f] hover:bg-[#7ebd7e] text-white text-xs font-bold rounded-full transition-colors disabled:opacity-50">
                        {qwenBusy ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />} 启动
                      </button>
                    )}
                    <button onClick={() => { fetchQwenStatus(); fetchQwenVoices(); fetchEmotions(); fetchQwenInstall(); fetchQwenModelStatus(); }} disabled={qwenBusy || qwenStarting}
                      className="flex items-center gap-1.5 px-3 py-1.5 bg-[#4fa0d8] hover:bg-[#5db4f0] text-white text-xs font-bold rounded-full transition-colors disabled:opacity-50">
                      <RefreshCw size={13} /> 刷新
                    </button>
                  </div>
                </div>

                {qwenMsg && <p className="text-xs font-bold text-[#4fa0d8]">{qwenMsg}</p>}

                {/* 环境未就绪：一键安装（带网络镜像选项） */}
                {qwenStatus && qwenStatus.installed && !qwenStatus.env_ready && (
                  <div className="bg-white rounded-lg border border-[#e6d5b8] p-4 space-y-3">
                    <p className="text-xs text-[#7a6b5d] leading-relaxed">
                      Qwen3-TTS 的<b>独立环境</b>尚未安装（避免与 GPT-SoVITS 依赖冲突）。
                      一键安装会克隆项目自带运行时，<b>无需另装 Python</b>。</p>

                    {/* 安装进度 */}
                    {(qwenInstall?.running || (qwenInstall?.done && qwenInstall?.error)) && (
                      <div>
                        <div className="flex justify-between text-xs font-bold text-[#4a4036] mb-1">
                          <span className="truncate pr-2">{qwenInstall.step || '安装中…'}</span>
                          <span>{qwenInstall.percent || 0}%</span>
                        </div>
                        <div className="h-2 bg-[#e8decb] rounded-full overflow-hidden">
                          <div className="h-full bg-[#8fbf8f] transition-all" style={{ width: `${qwenInstall.percent || 0}%` }} />
                        </div>
                        {qwenInstall.error && <p className="text-xs text-[#ba3f42] mt-2">{qwenInstall.error}</p>}
                        {Array.isArray(qwenInstall.log) && qwenInstall.log.length > 0 && (
                          <pre className="mt-2 max-h-32 overflow-y-auto bg-[#2b2b2b] text-[#d4d4d4] text-[10px] p-2 rounded border border-black/20 whitespace-pre-wrap break-all">{qwenInstall.log.slice(-15).join('\n')}</pre>
                        )}
                      </div>
                    )}

                    {/* 网络选项（应对网络问题） */}
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                      <div>
                        <label className="block text-[11px] font-bold text-[#7a6b5d] mb-1">pip 镜像源（留空 = 清华）</label>
                        <input type="text" value={qwenInstallPipIndex} onChange={e => setQwenInstallPipIndex(e.target.value)}
                          placeholder="https://pypi.tuna.tsinghua.edu.cn/simple"
                          className="w-full bg-white border border-[#d9c5b2] rounded-md px-2 py-1.5 text-[11px] outline-none" />
                      </div>
                      <div>
                        <label className="block text-[11px] font-bold text-[#7a6b5d] mb-1">HuggingFace 端点（大陆建议 hf-mirror）</label>
                        <input type="text" value={qwenInstallHf} onChange={e => setQwenInstallHf(e.target.value)}
                          placeholder="留空 = 官方；大陆填 https://hf-mirror.com"
                          className="w-full bg-white border border-[#d9c5b2] rounded-md px-2 py-1.5 text-[11px] outline-none" />
                      </div>
                    </div>

                    <label className="flex items-center gap-2 text-[11px] text-[#7a6b5d] cursor-pointer">
                      <input type="checkbox" checked={qwenInstallWithModel} onChange={e => setQwenInstallWithModel(e.target.checked)} className="accent-[#8fbf8f]" />
                      顺带预下载模型权重（1.7B 约 6-7GB，仅首次需要，可稍后启动时再下载）
                    </label>

                    {/* torch 版本选择（首次安装自由选择，后续可在下方独立切换） */}
                    <div>
                      <label className="block text-[11px] font-bold text-[#7a6b5d] mb-1">torch 版本（按显卡类型选择）</label>
                      <select value={qwenInstallTorchVariant} onChange={e => setQwenInstallTorchVariant(e.target.value)}
                        className="w-full bg-white border border-[#d9c5b2] rounded-md px-2 py-1.5 text-[11px] outline-none">
                        <option value="cu126">CUDA 12.6（NVIDIA 显卡，约 2.4GB）</option>
                        <option value="cu124">CUDA 12.4（NVIDIA 显卡，约 2.4GB）</option>
                        <option value="cu121">CUDA 12.1（NVIDIA 显卡，约 2.3GB）</option>
                        <option value="directml">DirectML（AMD/Intel 核显+独显，实验性）</option>
                        <option value="cpu">仅 CPU（无显卡兜底，124MB）</option>
                      </select>
                      <p className="text-[10px] text-[#a89578] mt-1 leading-relaxed">
                        <b className="text-[#ba3f42]">CUDA 仅支持 NVIDIA 显卡</b>；AMD/Intel 显卡（核显、独显）请选「DirectML」（实验性，兼容性待验证）；无独立显卡选「仅 CPU」。
                      </p>
                    </div>

                    <button onClick={startQwenInstall} disabled={!!qwenInstall?.running}
                      className="flex items-center gap-1.5 px-4 py-2 bg-[#8fbf8f] hover:bg-[#7ebd7e] text-white text-xs font-bold rounded-full transition-colors disabled:opacity-50 shadow-sm">
                      {qwenInstall?.running ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}
                      {qwenInstall?.running ? '安装中…' : '一键安装环境'}
                    </button>
                    {qwenInstall?.running && (
                      <button onClick={() => cancelTask('环境安装')}
                        className="ml-2 flex items-center gap-1.5 px-4 py-2 bg-[#ba3f42] hover:bg-[#a03538] text-white text-xs font-bold rounded-full transition-colors shadow-sm">
                        <Square size={13} /> 停止安装
                      </button>
                    )}
                    <p className="text-[10px] text-[#a89578] leading-relaxed">
                      安装会复制项目自带 runtime（约 0.6GB）并联网安装 qwen-tts 等依赖；网络不畅时可切换镜像源。
                      完全无需用户手动安装 Python 或执行任何命令。
                    </p>
                  </div>
                )}

                {/* 运行时缺失提示（环境已装但 env 位置异常） */}
                {qwenStatus && qwenStatus.installed && qwenStatus.env_ready && !qwenStatus.runtime_ok && (
                  <p className="text-xs text-[#7a6b5d] leading-relaxed">
                    独立环境已安装但未在默认位置找到：<code className="break-all">{qwenStatus.runtime}</code><br />
                    可设置环境变量 <b>GWC_QWEN_TTS_RUNTIME</b> 指向该环境下的 python.exe。
                  </p>
                )}

                {/* 环境就绪但模型缺失：单独「下载模型」入口 */}
                {qwenStatus && qwenStatus.installed && qwenStatus.env_ready && !qwenStatus.model_ready && (
                  <div className="bg-amber-50 rounded-lg border border-amber-300 p-4 space-y-2">
                    <p className="text-xs text-[#7a6b5d] leading-relaxed">
                      ⚠️ 环境已安装，但<b>模型权重尚未下载</b>。直接启动会卡在模型下载，请先点下方按钮下载模型。
                    </p>
                    {/* 模型下载进度 */}
                    {(qwenModelDl?.running || (qwenModelDl?.done && qwenModelDl?.error)) && (
                      <div>
                        <div className="flex justify-between text-xs font-bold text-[#4a4036] mb-1">
                          <span className="truncate pr-2">{qwenModelDl.step || '下载中…'}</span>
                          <span>{qwenModelDl.percent || 0}%</span>
                        </div>
                        <div className="h-2 bg-[#e8decb] rounded-full overflow-hidden">
                          <div className="h-full bg-amber-500 transition-all" style={{ width: `${qwenModelDl.percent || 0}%` }} />
                        </div>
                        {qwenModelDl.error && <p className="text-xs text-[#ba3f42] mt-2">{qwenModelDl.error}</p>}
                        {Array.isArray(qwenModelDl.log) && qwenModelDl.log.length > 0 && (
                          <pre className="mt-2 max-h-28 overflow-y-auto bg-[#2b2b2b] text-[#d4d4d4] text-[10px] p-2 rounded whitespace-pre-wrap break-all">{qwenModelDl.log.slice(-12).join('\n')}</pre>
                        )}
                        {qwenModelDl.running && (
                          <button onClick={() => cancelTask('模型下载')}
                            className="mt-2 flex items-center gap-1 px-3 py-1 bg-[#ba3f42] hover:bg-[#a03538] text-white text-[10px] font-bold rounded-full">
                            <Square size={11} /> 停止下载
                          </button>
                        )}
                      </div>
                    )}
                    <button onClick={() => setShowModelDlg(true)} disabled={!!qwenModelDl?.running}
                      className="flex items-center gap-1.5 px-4 py-2 bg-amber-500 hover:bg-amber-600 text-white text-xs font-bold rounded-full transition-colors disabled:opacity-50 shadow-sm">
                      {qwenModelDl?.running ? <Loader2 size={13} className="animate-spin" /> : <Download size={13} />}
                      {qwenModelDl?.running ? '下载中…' : '下载模型'}
                    </button>
                  </div>
                )}

                {/* torch 版本管理 + 检查更新（环境就绪后显示） */}
                {qwenStatus && qwenStatus.installed && qwenStatus.env_ready && (
                  <div className="bg-[#f0f5f0] rounded-lg border border-[#cfe3cf] p-4 space-y-3">
                    <div className="flex items-center justify-between">
                      <label className="text-xs font-bold text-[#4a6b4a]">🧮 torch 版本管理</label>
                      <span className="text-[10px] text-[#6b8b6b]">
                        {torchInfo?.torch_info?.installed
                          ? `当前 ${torchInfo.torch_info.torch_version}（${torchInfo.torch_info.backend}）`
                          : '未安装'}
                      </span>
                    </div>

                    {/* GPU 类型说明 */}
                    <p className="text-[10px] text-[#6b8b6b] leading-relaxed bg-white/60 rounded px-2 py-1.5 border border-[#cfe3cf]">
                      <b className="text-[#ba3f42]">CUDA 仅支持 NVIDIA 显卡</b>；AMD / Intel 显卡（核显、独显）请选 <b>DirectML</b>（实验性，兼容性待验证）；无独立显卡选「仅 CPU」。
                    </p>

                    {/* torch 操作进度 + 停止按钮 */}
                    {(torchOp?.running || (torchOp?.done && torchOp?.error)) && (
                      <div>
                        <div className="flex justify-between text-xs font-bold text-[#4a4036] mb-1">
                          <span className="truncate pr-2">{torchOp.step || '处理中…'}</span>
                          <span>{torchOp.percent || 0}%</span>
                        </div>
                        <div className="h-2 bg-[#e8decb] rounded-full overflow-hidden">
                          <div className="h-full bg-[#4fa0d8] transition-all" style={{ width: `${torchOp.percent || 0}%` }} />
                        </div>
                        {torchOp.error && <p className="text-xs text-[#ba3f42] mt-2">{torchOp.error}</p>}
                        {torchOp.running && (
                          <button onClick={() => cancelTask('torch 操作')}
                            className="mt-2 flex items-center gap-1 px-3 py-1 bg-[#ba3f42] hover:bg-[#a03538] text-white text-[10px] font-bold rounded-full">
                            <Square size={11} /> 停止
                          </button>
                        )}
                      </div>
                    )}

                    <div className="space-y-1.5">
                      {(torchInfo?.variants || []).map(v => {
                        // 当前变体判断：按 gpu_type 分组（nvidia=CUDA→variant="gpu"，directml→variant="directml"，cpu→variant="cpu"）
                        const curVariant = torchInfo?.torch_info?.variant;
                        const isCurrent = v.gpu_type === 'cpu'
                          ? curVariant === 'cpu'
                          : v.gpu_type === 'directml'
                            ? curVariant === 'directml'
                            : curVariant === 'gpu';
                        return (
                          <div key={v.id} className="flex items-center justify-between gap-2 bg-white rounded px-2 py-1.5 border border-[#e6d5b8]">
                            <div className="min-w-0">
                              <span className="text-[11px] font-bold text-[#4a4036]">{v.label}</span>
                              <span className="ml-2 text-[10px] text-[#a89578]">{v.desc}</span>
                            </div>
                            <div className="flex items-center gap-1 shrink-0">
                              {isCurrent && <span className="text-[10px] text-emerald-600 font-bold">当前</span>}
                              <button onClick={() => switchTorch(v.id)} disabled={!!torchOp?.running}
                                className="px-2 py-1 bg-[#4fa0d8] hover:bg-[#5db4f0] text-white text-[10px] font-bold rounded-full disabled:opacity-50">
                                切换
                              </button>
                              {/* 卸载按钮放切换按钮后，仅对「当前」版本显示 */}
                              {isCurrent && torchInfo?.torch_info?.installed && (
                                <button onClick={uninstallTorch} disabled={!!torchOp?.running} title={`卸载当前 ${v.label}`}
                                  className="px-2 py-1 bg-[#f5e6e6] hover:bg-[#eabfbf] text-[#ba3f42] text-[10px] font-bold rounded-full disabled:opacity-40">
                                  卸载
                                </button>
                              )}
                            </div>
                          </div>
                        );
                      })}
                    </div>

                    <div className="flex flex-wrap gap-2 pt-1">
                      <button onClick={checkUpdates} disabled={checkingUpdate}
                        className="flex items-center gap-1 px-3 py-1.5 bg-[#f0e8db] hover:bg-[#e6dccb] text-[#4a4036] text-[11px] font-bold rounded-full disabled:opacity-50">
                        {checkingUpdate ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />} 检查更新
                      </button>
                    </div>

                    {/* 检查更新结果 + 更新按钮 */}
                    {updates && (
                      <div className="bg-white rounded border border-[#e6d5b8] p-2 space-y-1">
                        {!updates.ok && <p className="text-[11px] text-[#ba3f42]">{updates.msg || '检查失败'}</p>}
                        {updates.ok && (updates.items || []).map(it => (
                          <div key={it.package} className="flex items-center justify-between gap-2 text-[11px]">
                            <span className="font-bold text-[#4a4036] shrink-0">{it.label}</span>
                            <span className="flex-1 text-right">
                              <span className="text-[#7a6b5d]">{it.current || '未安装'}</span>
                              {it.locked ? (
                                <span className="ml-2 text-[#a89578]">🔒 锁定</span>
                              ) : it.update_available ? (
                                <span className="ml-2 text-amber-600 font-bold">→ {it.latest}</span>
                              ) : (
                                <span className="ml-2 text-emerald-600">✓ 最新</span>
                              )}
                            </span>
                            {it.update_available && !it.locked && (
                              <button onClick={() => updatePackage(it.package)} disabled={!!torchOp?.running}
                                className="shrink-0 px-2 py-0.5 bg-[#8fbf8f] hover:bg-[#7ebd7e] text-white text-[10px] font-bold rounded-full disabled:opacity-50">
                                更新
                              </button>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {/* 硬件检测 + 手动纠错 */}
                {qwenStatus && qwenStatus.installed && qwenStatus.env_ready && (
                  <div className="bg-[#eef4ee] rounded-lg border border-[#cfe3cf] p-4 space-y-3">
                    <div className="flex items-center justify-between">
                      <label className="text-xs font-bold text-[#4a6b4a]">🔍 硬件检测</label>
                      <button onClick={fetchHardware} className="text-[10px] text-[#4fa0d8] hover:underline">重新检测</button>
                    </div>

                    {/* GPU 列表 */}
                    {(hardware?.gpus?.length || 0) > 0 ? (
                      <div className="space-y-1.5">
                        {hardware.gpus.map((g, i) => (
                          <div key={i} className="flex items-center justify-between bg-white rounded px-2 py-1.5 border border-[#e6d5b8]">
                            <span className="text-[11px] font-bold text-[#4a4036]">
                              {g.vendor === 'NVIDIA' ? '🟢 NVIDIA' : g.vendor === 'AMD' ? '🔴 AMD' : g.vendor === 'Intel' ? '🔵 Intel（核显）' : '⚪ ' + g.vendor}
                              {' · '}{g.name}
                            </span>
                            <span className="text-[10px] text-[#a89578]">{g.vram_mb > 0 ? `${g.vram_mb}MB 显存` : ''}</span>
                          </div>
                        ))}
                        {hardware.multi_gpu && (
                          <p className="text-[10px] text-amber-600 leading-relaxed">
                            ⚠️ 检测到多张显卡（含核显）。CUDA 环境默认使用 <b>NVIDIA 独显</b>；DirectML 环境可指定使用核显或独显（在下方手动选择）。请确保系统在「显卡控制面板」里将本程序分配给正确的显卡。
                          </p>
                        )}
                      </div>
                    ) : (
                      <p className="text-[11px] text-[#a89578]">未检测到 GPU（可能无独立显卡），将使用 CPU。</p>
                    )}

                    {/* 手动纠错 */}
                    <div>
                      <label className="block text-[11px] font-bold text-[#7a6b5d] mb-1">手动纠错（若检测有误可手动选择 GPU 类型）</label>
                      <div className="flex flex-wrap gap-1.5">
                        {[
                          { v: '', l: '自动检测' },
                          { v: 'nvidia', l: 'NVIDIA 独显（GTX/RTX）' },
                          { v: 'amd', l: 'AMD 独显（RX）' },
                          { v: 'intel', l: 'Intel 核显' },
                          { v: 'amd_igpu', l: 'AMD 核显' },
                        ].map(o => (
                          <button key={o.v} onClick={() => setManualGpu(o.v)}
                            className={`px-2 py-1 rounded-full text-[10px] font-bold border ${manualGpu === o.v ? 'bg-[#8fbf8f] text-white border-[#8fbf8f]' : 'bg-white text-[#4a4036] border-[#e6d5b8]'}`}>
                            {o.l}
                          </button>
                        ))}
                      </div>
                      <p className="text-[10px] text-[#a89578] mt-1">
                        建议：NVIDIA 独显 → CUDA；AMD/Intel（核显+独显）→ DirectML。手动选择只影响推荐展示，不改变已安装环境。
                      </p>
                    </div>

                    {/* torch 镜像选择 */}
                    {torchMirrors.length > 0 && (
                      <div>
                        <label className="block text-[11px] font-bold text-[#7a6b5d] mb-1">torch 下载镜像（CUDA 版）</label>
                        <select value={torchMirror} onChange={e => setTorchMirror(e.target.value)}
                          className="w-full bg-white border border-[#d9c5b2] rounded-md px-2 py-1.5 text-[11px] outline-none">
                          {torchMirrors.map(m => <option key={m.id} value={m.id}>{m.label}</option>)}
                        </select>
                      </div>
                    )}
                  </div>
                )}

                {/* Qwen3 模型管理 */}
                {qwenStatus && qwenStatus.installed && qwenStatus.env_ready && (
                  <div className="bg-[#eef4ee] rounded-lg border border-[#cfe3cf] p-4 space-y-3">
                    <div className="flex items-center justify-between">
                      <label className="text-xs font-bold text-[#4a6b4a]">📦 Qwen3-TTS 模型管理</label>
                      <button onClick={fetchQwenModels} className="text-[10px] text-[#4fa0d8] hover:underline">刷新</button>
                    </div>
                    <div className="space-y-1.5">
                      {(qwenModels?.models || []).map(m => (
                        <div key={m.id} className="flex items-center justify-between gap-2 bg-white rounded px-2 py-1.5 border border-[#e6d5b8]">
                          <div className="min-w-0">
                            <span className="text-[11px] font-bold text-[#4a4036]">{m.label}</span>
                            <span className="ml-2 text-[10px] text-[#a89578]">{m.size_desc} · {m.vram_desc}</span>
                            <div className="text-[10px] text-[#a89578]">{m.note}</div>
                          </div>
                          <div className="flex items-center gap-1 shrink-0">
                            {m.is_current ? <span className="text-[10px] text-emerald-600 font-bold">当前</span> : null}
                            {m.downloaded ? <span className="text-[10px] text-[#4fa0d8]">已下载</span> : <span className="text-[10px] text-[#a89578]">未下载</span>}
                            {!m.is_current && (
                              <button onClick={() => switchQwenModel(m.id)}
                                className="px-2 py-1 bg-[#4fa0d8] hover:bg-[#5db4f0] text-white text-[10px] font-bold rounded-full">
                                切换
                              </button>
                            )}
                            {m.downloaded && (
                              <button onClick={() => uninstallQwenModel(m.id)}
                                className="px-2 py-1 bg-[#f5e6e6] hover:bg-[#eabfbf] text-[#ba3f42] text-[10px] font-bold rounded-full">
                                卸载
                              </button>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                    <p className="text-[10px] text-[#a89578] leading-relaxed">
                      切换模型后需<b>重启 Qwen3-TTS</b>才生效；未下载的模型会在下次启动时自动下载（或用「下载模型」按钮）。tokenizer（{qwenModels?.tokenizer}）是固定配套，不可卸载。
                    </p>
                  </div>
                )}

                {/* 情绪模板选择（Qwen3 独有能力） */}
                <div>
                  <label className="text-xs font-bold text-[#7a6b5d]">情绪模板 (instruct) — 一句话控制语气</label>
                  <div className="flex flex-wrap gap-2 mt-2">
                    {emotions.length === 0 ? (
                      <p className="text-[11px] text-[#a89578]">服务未运行时不可选；默认「平静」。</p>
                    ) : emotions.map(em => (
                      <button key={em.id} onClick={() => setSettings({ ...settings, ttsQwenEmotion: em.id })}
                        title={em.instruct}
                        className={`px-3 py-1.5 rounded-full text-xs font-bold border transition-colors ${
                          settings.ttsQwenEmotion === em.id
                            ? 'bg-[#8fbf8f] text-white border-[#8fbf8f]'
                            : 'bg-white text-[#4a4036] border-[#e6d5b8] hover:border-[#8fbf8f]'
                        }`}>
                        {em.name}
                      </button>
                    ))}
                  </div>
                  <p className="text-[10px] text-[#a89578] mt-1">情绪仅对 Qwen3-TTS 生效（GPT-SoVITS 情感依赖参考音频）。</p>
                </div>

                {/* 音色管理（快速添加 + 实时切换 + 删除） */}
                {qwenStatus?.running && (
                  <div className="space-y-3">
                    <div className="flex items-center justify-between mb-1">
                      <label className="text-xs font-bold text-[#7a6b5d]">音色管理（零训练克隆）</label>
                      <button onClick={fetchQwenVoices} className="flex items-center gap-1 px-2 py-1 bg-[#4fa0d8] hover:bg-[#5db4f0] text-white text-[10px] font-bold rounded-full">
                        <RefreshCw size={11} /> 刷新
                      </button>
                    </div>

                    {/* 快速添加/编辑音色 */}
                    <div id="qwen-voice-add-form" className="bg-white rounded-lg border border-[#e6d5b8] p-3 space-y-2">
                      <label className="text-[11px] font-bold text-[#4a4036]">
                        {qwenVoiceForm.id && qwenVoices.some(x => x.id === qwenVoiceForm.id) ? '✏️ 编辑音色（保存将覆盖更新）' : '➕ 快速添加音色'}
                      </label>
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                        <input type="text" value={qwenVoiceForm.id} onChange={e => setQwenVoiceForm({ ...qwenVoiceForm, id: e.target.value })}
                          placeholder="音色名（如 ATRI）"
                          className="bg-white border border-[#d9c5b2] rounded-md px-2 py-1.5 text-[11px] outline-none" />
                        <input type="file" accept="audio/*" onChange={e => setQwenVoiceFile(e.target.files[0] || null)}
                          className="block text-[11px] text-[#7a6b5d] file:mr-2 file:py-1 file:px-2 file:rounded-full file:border-0 file:text-[10px] file:bg-[#8fbf8f] file:text-white" />
                      </div>
                      <textarea value={qwenVoiceForm.text} onChange={e => setQwenVoiceForm({ ...qwenVoiceForm, text: e.target.value })}
                        placeholder="参考音频文字稿（逐字精确，克隆质量关键）"
                        rows={2} className="w-full bg-white border border-[#d9c5b2] rounded-md px-2 py-1.5 text-[11px] outline-none resize-none" />
                      <div className="flex items-center gap-2">
                        <button onClick={saveQwenVoice} disabled={qwenVoiceSaving}
                          className="flex items-center gap-1 px-3 py-1.5 bg-[#8fbf8f] hover:bg-[#7ebd7e] text-white text-[11px] font-bold rounded-full disabled:opacity-50">
                          {qwenVoiceSaving ? <Loader2 size={11} className="animate-spin" /> : null}
                          {qwenVoiceForm.id && qwenVoices.some(x => x.id === qwenVoiceForm.id) ? '更新音色' : '保存音色'}
                        </button>
                        {qwenVoiceForm.id && (
                          <button onClick={() => setQwenVoiceForm({ id: '', text: '' })} className="text-[10px] text-[#7a6b5d] hover:underline">取消编辑</button>
                        )}
                      </div>
                      <p className="text-[10px] text-[#a89578] leading-relaxed">
                        参考音频建议 <b>3-10 秒、单说话人、无背景噪音</b>；文字稿逐字精确。克隆不像时请检查这两项。
                      </p>
                    </div>

                    {/* 音色列表 */}
                    {qwenVoices.length === 0 ? (
                      <p className="text-xs text-[#a89578]">未发现音色。用上方「快速添加音色」上传参考音频 + 文字稿。</p>
                    ) : (
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                        {qwenVoices.map(v => {
                          const ai = v.audio_info || {};
                          const badDur = ai.seconds && (ai.seconds < 2 || ai.seconds > 15);
                          const badCh = ai.channels && ai.channels > 1;
                          return (
                          <div key={v.id} className={`flex flex-col justify-between gap-1 text-left px-3 py-2 rounded-lg text-xs font-bold border ${settings.ttsQwenVoiceId === v.id ? 'bg-[#8fbf8f]/10 border-[#8fbf8f]' : 'bg-white border-[#e6d5b8]'}`}>
                            <div className="flex items-center justify-between gap-1">
                              <button onClick={() => v.usable && switchQwenVoice(v.id)} disabled={!v.usable || !!qwenVoiceBusy}
                                title={v.usable ? '点击切换音色' : '缺少参考音频或文字稿'}
                                className="flex items-center gap-1 text-left flex-1 disabled:opacity-40">
                                <span className="font-black text-[#4a4036]">{v.name}</span>
                                {settings.ttsQwenVoiceId === v.id && <CheckCircle size={11} className="text-[#8fbf8f]" />}
                                {!v.usable && <span className="ml-1 text-[10px] font-normal text-[#a89578]">缺素材</span>}
                              </button>
                              <div className="flex items-center gap-1 shrink-0">
                                <button onClick={() => editQwenVoice(v)} title="编辑音色"
                                  className="p-1 text-[#4fa0d8] hover:bg-[#e8f1fa] rounded"><Pencil size={12} /></button>
                                <button onClick={() => deleteQwenVoice(v.id)} title="删除音色"
                                  className="p-1 text-[#ba3f42] hover:bg-[#f5e6e6] rounded"><Trash2 size={12} /></button>
                              </div>
                            </div>
                            {/* 参考音频属性提示（帮助判断是否混音/正确） */}
                            {(ai.seconds || ai.channels) && (
                              <div className="text-[9px] text-[#a89578] flex items-center gap-2">
                                <span>{ai.seconds ? `⏱ ${ai.seconds}s` : ''}{ai.sample_rate ? ` / ${ai.sample_rate}Hz` : ''}{ai.channels ? ` / ${ai.channels}声道` : ''}</span>
                                {badCh && <span className="text-amber-600 font-bold">⚠ 多声道</span>}
                                {badDur && <span className="text-amber-600 font-bold">⚠ 时长非 3-10s</span>}
                              </div>
                            )}
                          </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                )}

                <p className="text-[11px] text-[#7a6b5d] leading-relaxed border-t border-dashed border-[#e6d5b8] pt-3">
                  基于阿里 Qwen3-TTS，支持零训练声音复刻与自然语言情绪控制。服务地址为 <code>127.0.0.1:9881</code>。
                  需独立 Python 3.12 环境与 8GB 显存（1.7B 版），详见 <code>tts-qwen3/README.md</code>。
                </p>
              </div>
            )}
            {settings.ttsEngine === 'sovits' && (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="md:col-span-2"><label className="block text-xs text-[#7a6b5d] mb-1 font-bold">参考音频路径/URL</label><input type="text" value={settings.ttsRefAudio || ''} onChange={e => setSettings({...settings, ttsRefAudio: e.target.value})} className="w-full bg-white border border-[#d9c5b2] text-[#4a4036] rounded-md px-3 py-2 text-sm outline-none shadow-inner" placeholder="如: D:\audio\ref.wav" /></div>
              <div><label className="block text-xs text-[#7a6b5d] mb-1 font-bold">参考音频语种</label><select value={settings.ttsRefLang || 'zh'} onChange={e => setSettings({...settings, ttsRefLang: e.target.value})} className="w-full bg-white border border-[#d9c5b2] text-[#4a4036] font-bold rounded-md px-3 py-2 outline-none shadow-inner"><option value="zh">中文</option><option value="ja">日文</option><option value="en">英文</option><option value="ko">韩文</option></select></div>
              <div className="md:col-span-3"><label className="block text-xs text-[#7a6b5d] mb-1 font-bold">参考音频文本</label><input type="text" value={settings.ttsRefText || ''} onChange={e => setSettings({...settings, ttsRefText: e.target.value})} className="w-full bg-white border border-[#d9c5b2] text-[#4a4036] rounded-md px-3 py-2 text-sm outline-none shadow-inner" placeholder="参考音频里说的话..." /></div>
            </div>
            )}
            <p className="text-[11px] text-[#7a6b5d] mt-2">{settings.ttsEngine === 'sovits' ? '留空则不传参考音频参数，由服务端使用自身配置的默认音色。' : 'Qwen3-TTS 音色与情绪在上述「内置配音服务 (Qwen3-TTS)」控制台配置，无需此处参考音频参数。'}</p>
          </div>
        </div>
      </div>

      {/* 同声传译 */}
      <SettingSectionTitle title="同声传译设定" />
      <div className="bg-white/60 p-6 rounded-xl border border-[#e6d5b8] shadow-sm space-y-4">
        <SettingToggle label="启用同声传译模式" value={settings.enableTranslation} onChange={v => setSettings({...settings, enableTranslation: v})} />
        <p className="text-xs text-[#7a6b5d]">开启后，AI 分别生成外文语音与母语文本。</p>
        {settings.enableTranslation && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 pt-4 border-t border-dashed border-[#e6d5b8]">
            <div><label className="block text-sm font-bold text-[#ba3f42] mb-2">屏幕显示语种</label><select value={settings.displayLanguage} onChange={e => setSettings({...settings, displayLanguage: e.target.value})} className="w-full bg-white border border-[#d9c5b2] text-[#4a4036] font-bold rounded-md px-3 py-2 outline-none shadow-inner"><option value="zh">中文</option><option value="ja">日文</option><option value="en">英文</option><option value="ko">韩文</option></select></div>
            <div><label className="block text-sm font-bold text-[#ba3f42] mb-2">语音合成语种</label><select disabled value={settings.ttsLanguage} className="w-full bg-[#fdfaf5] border border-[#e6d5b8] text-[#a89578] font-bold rounded-md px-3 py-2 outline-none shadow-inner cursor-not-allowed"><option value="zh">中文</option><option value="ja">日文</option><option value="en">英文</option><option value="ko">韩文</option></select></div>
          </div>
        )}
      </div>

      {/* 按钮点击音效 */}
      <SettingSectionTitle title="按钮点击音效 (UI Click Sound)" />
      <div className="bg-white/60 p-6 rounded-xl border border-[#e6d5b8] shadow-sm space-y-5">
        <SettingToggle label="开启全局按钮点击音效" value={settings.uiClickSoundEnabled} onChange={v => setSettings({...settings, uiClickSoundEnabled: v})} />
        <p className="text-xs text-[#7a6b5d] leading-relaxed">
          开启后，全应用的按钮、链接、开关被点击时都会播放下方的自定义音效（对全局生效，包括设置页、标题界面、聊天界面等）。
        </p>

        <div className={`space-y-5 transition-opacity ${!settings.uiClickSoundEnabled && 'opacity-50 pointer-events-none'}`}>
          <div>
            <label className="block text-sm font-bold text-[#ba3f42] mb-2">自定义音效文件 (mp3 / wav / ogg)</label>
            <div className="flex flex-wrap items-center gap-3">
              <input
                type="file"
                accept="audio/*"
                onChange={async (e) => {
                  const f = e.target.files[0];
                  e.target.value = '';
                  if (!f) return;
                  if (f.size > 512 * 1024) { setSoundMsg({ ok: false, text: '文件过大（超过 512KB），请选择更短小的音效' }); return; }
                  try {
                    const dataUrl = await new Promise((res, rej) => {
                      const r = new FileReader();
                      r.onload = () => res(r.result);
                      r.onerror = rej;
                      r.readAsDataURL(f);
                    });
                    setSettings({ ...settings, uiClickSoundUrl: dataUrl });
                    setSoundMsg({ ok: true, text: `已加载音效：${f.name}（点击右侧试听）` });
                  } catch {
                    setSoundMsg({ ok: false, text: '读取文件失败' });
                  }
                }}
                className="block text-sm text-[#7a6b5d] file:mr-4 file:py-2 file:px-4 file:rounded-full file:border-0 file:text-sm file:font-bold file:bg-[#4fa0d8] file:text-white hover:file:bg-[#5db4f0] cursor-pointer"
              />
              {settings.uiClickSoundUrl && (
                <button
                  onClick={() => playClickSound(settings.uiClickSoundUrl, settings.uiClickSoundVolume)}
                  className="flex items-center gap-1.5 px-4 py-2 bg-[#8fbf8f] hover:bg-[#7ebd7e] text-white text-xs font-bold rounded-full transition-colors shadow-sm"
                >
                  <Play size={13} /> 试听
                </button>
              )}
              {settings.uiClickSoundUrl && (
                <button
                  onClick={() => setSettings({ ...settings, uiClickSoundUrl: '' })}
                  className="px-4 py-2 bg-[#f5e6e6] hover:bg-[#eabfbf] text-[#ba3f42] text-xs font-bold rounded-full transition-colors shadow-sm"
                >
                  移除音效
                </button>
              )}
            </div>
            {soundMsg && (
              <p className={`text-xs mt-2 font-bold ${soundMsg.ok ? 'text-emerald-600' : 'text-[#ba3f42]'}`}>{soundMsg.text}</p>
            )}
            {!settings.uiClickSoundUrl && (
              <p className="text-[11px] text-[#a89578] mt-2">建议使用 0.05 ~ 0.3 秒的短促音效，文件不超过 512KB。设置后立即对全局按钮生效。</p>
            )}
          </div>

          <SettingSlider
            label="点击音效音量"
            value={settings.uiClickSoundVolume ?? 0.5}
            min={0} max={1} step={0.05}
            onChange={v => setSettings({...settings, uiClickSoundVolume: v})}
          />
        </div>
      </div>

      {/* 模型下载弹窗：选择下载源（HF / hf-mirror / ModelScope） */}
      {showModelDlg && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/50 backdrop-blur-sm" onClick={() => setShowModelDlg(false)}>
          <div className="bg-white rounded-2xl border border-[#e6d5b8] shadow-2xl p-6 w-[min(92vw,500px)] space-y-4 max-h-[90vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
            <div className="flex items-center gap-2">
              <Globe size={18} className="text-[#4fa0d8]" />
              <h3 className="text-base font-black text-[#4a4036]">下载 Qwen3-TTS 模型</h3>
            </div>
            <p className="text-xs text-[#7a6b5d] leading-relaxed">
              将下载 <b>Qwen/Qwen3-TTS-12Hz-1.7B-Base</b>（约 6-7GB）与 <b>Qwen/Qwen3-TTS-Tokenizer-12Hz</b>（约 1GB）到本机缓存。
            </p>

            {/* 下载源选择 */}
            <div>
              <label className="block text-xs font-bold text-[#7a6b5d] mb-1">下载源</label>
              <div className="grid grid-cols-1 gap-2">
                <button onClick={() => setModelSource('modelscope')}
                  className={`text-left px-3 py-2 rounded-lg text-xs font-bold border transition-colors ${modelSource === 'modelscope' ? 'bg-[#8fbf8f]/15 border-[#8fbf8f] text-[#4a7a4a]' : 'bg-white border-[#e6d5b8] text-[#4a4036]'}`}>
                  🚀 ModelScope 阿里魔搭（推荐，国内直连快）
                </button>
                <button onClick={() => setModelSource('auto')}
                  className={`text-left px-3 py-2 rounded-lg text-xs font-bold border transition-colors ${modelSource === 'auto' ? 'bg-[#4fa0d8]/10 border-[#4fa0d8] text-[#4fa0d8]' : 'bg-white border-[#e6d5b8] text-[#4a4036]'}`}>
                  🔄 自动（先 HF 镜像，失败回退 ModelScope）
                </button>
                <button onClick={() => setModelSource('hf')}
                  className={`text-left px-3 py-2 rounded-lg text-xs font-bold border transition-colors ${modelSource === 'hf' ? 'bg-[#4fa0d8]/10 border-[#4fa0d8] text-[#4fa0d8]' : 'bg-white border-[#e6d5b8] text-[#4a4036]'}`}>
                  🌐 HuggingFace（官方 / 自定义镜像）
                </button>
              </div>
            </div>

            {/* HF 端点（仅选 HF 源时显示） */}
            {modelSource === 'hf' && (
              <div>
                <label className="block text-xs font-bold text-[#7a6b5d] mb-1">HuggingFace 端点</label>
                <div className="flex gap-2 mb-2">
                  <button onClick={() => setModelHfEndpoint('')}
                    className={`flex-1 px-3 py-2 rounded-lg text-xs font-bold border transition-colors ${modelHfEndpoint === '' ? 'bg-[#4fa0d8]/10 border-[#4fa0d8] text-[#4fa0d8]' : 'bg-white border-[#e6d5b8] text-[#4a4036]'}`}>
                    官方源
                  </button>
                  <button onClick={() => setModelHfEndpoint('https://hf-mirror.com')}
                    className={`flex-1 px-3 py-2 rounded-lg text-xs font-bold border transition-colors ${modelHfEndpoint === 'https://hf-mirror.com' ? 'bg-[#4fa0d8]/10 border-[#4fa0d8] text-[#4fa0d8]' : 'bg-white border-[#e6d5b8] text-[#4a4036]'}`}>
                    hf-mirror
                  </button>
                </div>
                <input type="text" value={modelHfEndpoint}
                  onChange={e => setModelHfEndpoint(e.target.value)}
                  placeholder="留空 = 官方；或自定义镜像端点"
                  className="w-full bg-white border border-[#d9c5b2] rounded-md px-3 py-2 text-xs outline-none" />
              </div>
            )}

            <p className="text-[10px] text-[#a89578]">
              {modelSource === 'modelscope' ? 'ModelScope 是阿里出品，Qwen 模型国内直连下载最快最稳。' :
               modelSource === 'auto' ? '自动模式会先尝试 HF（含镜像），失败自动切换到 ModelScope。' :
               'HF 官方和 hf-mirror 在大陆常超时，若失败建议改用 ModelScope 源。'}
            </p>

            <div className="flex justify-end gap-2">
              <button onClick={() => setShowModelDlg(false)}
                className="px-4 py-2 bg-[#f0e8db] hover:bg-[#e6dccb] text-[#4a4036] text-xs font-bold rounded-full transition-colors">
                取消
              </button>
              <button onClick={startModelDownload}
                className="flex items-center gap-1.5 px-5 py-2 bg-[#8fbf8f] hover:bg-[#7ebd7e] text-white text-xs font-bold rounded-full transition-colors shadow-sm">
                <Download size={13} /> 开始下载
              </button>
            </div>
          </div>
        </div>
      )}
      {/* 文档弹窗：GPT-SoVITS / Qwen3-TTS 配置说明 */}
      {showDoc && (
        <div className="fixed inset-0 z-[110] flex items-center justify-center bg-black/50 backdrop-blur-sm" onClick={() => setShowDoc(null)}>
          <div className="bg-white rounded-2xl border border-[#e6d5b8] shadow-2xl p-6 w-[min(95vw,720px)] max-h-[88vh] overflow-y-auto space-y-4" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between">
              <h3 className="text-base font-black text-[#4a4036]">
                {showDoc === 'sovits' ? '📘 GPT-SoVITS 配置文档' : '📘 Qwen3-TTS 配置文档'}
              </h3>
              <button onClick={() => setShowDoc(null)} className="p-1 text-[#a89578] hover:text-[#4a4036]"><X size={18} /></button>
            </div>

            {showDoc === 'sovits' ? (
              <div className="space-y-4 text-xs text-[#4a4036] leading-relaxed">
                <div>
                  <h4 className="font-black text-[#ba3f42] mb-1">一、优缺点</h4>
                  <p>✅ <b>优点</b>：音色复刻保真度高（需训练），情感通过参考音频自然还原；本地推理，数据不出机；社区成熟，中文/日语素材丰富。</p>
                  <p>❌ <b>缺点</b>：需<b>先训练</b>才能复刻新音色（耗时数小时+GPU）；情感依赖参考音频（无法一句话指定）；首包延迟较高（模型加载 + 切句）。</p>
                </div>
                <div>
                  <h4 className="font-black text-[#ba3f42] mb-1">二、需求配置</h4>
                  <p>• Python 3.9-3.11（本项目共享原 GPT-SoVITS 安装目录的 runtime）</p>
                  <p>• NVIDIA GPU（推荐 6GB+ 显存）；也支持 CPU（慢）</p>
                  <p>• 已训练的 `.ckpt`（GPT）+ `.pth`（SoVITS）音色权重，放到 <code className="bg-gray-100 px-1 rounded">tts/models/gpt</code> 和 <code className="bg-gray-100 px-1 rounded">tts/models/sovits</code></p>
                </div>
                <div>
                  <h4 className="font-black text-[#ba3f42] mb-1">三、如何更改安装配置</h4>
                  <p>• 运行时路径：环境变量 <code className="bg-gray-100 px-1 rounded">GWC_SOVITS_RUNTIME</code> 指向 <code className="bg-gray-100 px-1 rounded">runtime\python.exe</code></p>
                  <p>• 端口：默认 9880，在 <code className="bg-gray-100 px-1 rounded">tts/start_tts.bat</code> 中改 <code className="bg-gray-100 px-1 rounded">-p</code> 参数</p>
                </div>
                <div>
                  <h4 className="font-black text-[#ba3f42] mb-1">四、手动配置（自动安装失败时）</h4>
                  <p>1. 下载 GPT-SoVITS 整合包：<a className="text-blue-600 underline" href="https://github.com/RVC-Boss/GPT-SoVITS" target="_blank" rel="noreferrer">https://github.com/RVC-Boss/GPT-SoVITS</a></p>
                  <p>2. 解压后，本项目设置页 → 声音设定 → 内置配音 → 扫描本机 GPT-SoVITS 一键导入（只复制推理最小集）</p>
                  <p>3. 音色权重放 <code className="bg-gray-100 px-1 rounded">tts/models/gpt</code> / <code className="bg-gray-100 px-1 rounded">tts/models/sovits</code>，参考音频放 <code className="bg-gray-100 px-1 rounded">tts/ref_audio</code></p>
                </div>
                <div>
                  <h4 className="font-black text-[#ba3f42] mb-1">五、交给 AI Agent 自动配置（Opencode）</h4>
                  <p className="mb-1">打开 Opencode，工作区设为项目根目录 <code className="bg-gray-100 px-1 rounded">GWC-Pro-End</code>，复制以下提示词：</p>
                  <pre className="bg-gray-900 text-gray-100 text-[10px] p-3 rounded whitespace-pre-wrap break-all select-all">请帮我在本项目配置 GPT-SoVITS 内置配音：1) 检查 tts/server/api_v2.py 与 tts/models 下的音色权重是否齐全；2) 若缺失，请根据 README 从本机 GPT-SoVITS 安装目录复制推理最小集；3) 确认 backend/main.py 中 _tts_runtime_path() 指向正确的 runtime\python.exe；4) 启动 tts 服务并验证 /api/tts/status 返回 running=true。工作区：GWC-Pro-End</pre>
                </div>
              </div>
            ) : (
              <div className="space-y-4 text-xs text-[#4a4036] leading-relaxed">
                <div>
                  <h4 className="font-black text-[#ba3f42] mb-1">一、优缺点</h4>
                  <p>✅ <b>优点</b>：<b>零训练</b>声音克隆（3 秒参考音频即可）；情感一句话指定（instruct）；流式首包 97ms；中日英韩等 10 语言。</p>
                  <p>❌ <b>缺点</b>：需 NVIDIA GPU（CUDA）才能流畅推理；1.7B 模型约 4.5GB 显存+7GB 占用；大陆下载模型/torch 需镜像。</p>
                </div>
                <div>
                  <h4 className="font-black text-[#ba3f42] mb-1">二、需求配置</h4>
                  <p>• 独立 Python 3.11 环境（本项目克隆 backend/runtime，免装 Python）</p>
                  <p>• <b>NVIDIA GPU</b>：CUDA 12.x（30/40/50 系 RTX 均可），8GB 显存推荐跑 1.7B</p>
                  <p>• <b>AMD/Intel 显卡</b>：DirectML（实验性，兼容性待验证）</p>
                  <p>• 模型：1.7B-Base（推荐）或 0.6B-Base（低显存）；tokenizer 固定</p>
                </div>
                <div>
                  <h4 className="font-black text-[#ba3f42] mb-1">三、如何更改安装配置（按显卡）</h4>
                  <p>• <b>NVIDIA RTX 30/40/50 系</b>：torch 版本选 <b>CUDA 12.6</b>（cu126），镜像选「上海交大 SJTUG」</p>
                  <p>• <b>AMD 独显（RX）/AMD 核显</b>：torch 版本选 <b>DirectML</b>（装 torch-directml）</p>
                  <p>• <b>Intel 核显</b>：选 DirectML（或仅 CPU 兜底）</p>
                  <p>• 显存不足 6GB：模型选 <b>0.6B-Base</b></p>
                </div>
                <div>
                  <h4 className="font-black text-[#ba3f42] mb-1">四、手动配置（自动安装失败时）</h4>
                  <p>1. 模型下载（国内用 ModelScope，快）：</p>
                  <p className="pl-3">• 1.7B：<a className="text-blue-600 underline" href="https://www.modelscope.cn/models/Qwen/Qwen3-TTS-12Hz-1.7B-Base" target="_blank" rel="noreferrer">modelscope.cn/.../Qwen3-TTS-12Hz-1.7B-Base</a></p>
                  <p className="pl-3">• 0.6B：<a className="text-blue-600 underline" href="https://www.modelscope.cn/models/Qwen/Qwen3-TTS-12Hz-0.6B-Base" target="_blank" rel="noreferrer">modelscope.cn/.../Qwen3-TTS-12Hz-0.6B-Base</a></p>
                  <p className="pl-3">• tokenizer：<a className="text-blue-600 underline" href="https://www.modelscope.cn/models/Qwen/Qwen3-TTS-Tokenizer-12Hz" target="_blank" rel="noreferrer">modelscope.cn/.../Qwen3-TTS-Tokenizer-12Hz</a></p>
                  <p>2. 下载后放到 <code className="bg-gray-100 px-1 rounded">tts-qwen3/models/models--Qwen--&lt;型号&gt;/snapshots/&lt;revision&gt;/</code>（需保留 HF 缓存目录结构）</p>
                  <p>3. torch CUDA 手动装：<code className="bg-gray-100 px-1 rounded">tts-qwen3\env\python.exe -m pip install torch torchaudio --index-url https://mirrors.sjtug.sjtu.edu.cn/pytorch-wheels/cu126 --timeout 20 --retries 15</code></p>
                  <p>4. torch DirectML：<code className="bg-gray-100 px-1 rounded">tts-qwen3\env\python.exe -m pip install torch-directml</code></p>
                </div>
                <div>
                  <h4 className="font-black text-[#ba3f42] mb-1">五、交给 AI Agent 自动配置（Opencode）</h4>
                  <p className="mb-1">打开 Opencode，工作区设为项目根目录 <code className="bg-gray-100 px-1 rounded">GWC-Pro-End</code>，复制以下提示词：</p>
                  <pre className="bg-gray-900 text-gray-100 text-[10px] p-3 rounded whitespace-pre-wrap break-all select-all">请帮我在本项目配置 Qwen3-TTS：1) 检查 tts-qwen3/env 是否已有 qwen-tts 和 torch，若无则用 backend/runtime 克隆 env 并 pip install qwen-tts fastapi uvicorn soundfile numpy；2) 检查 tts-qwen3/models 下是否已有 Qwen/Qwen3-TTS-12Hz-1.7B-Base 与 Qwen/Qwen3-TTS-Tokenizer-12Hz 权重，若无则用 ModelScope 下载到 HF 缓存结构；3) 按显卡装 torch：NVIDIA 用 --index-url https://mirrors.sjtug.sjtu.edu.cn/pytorch-wheels/cu126，AMD/Intel 用 pip install torch-directml；4) 启动 tts-qwen3/server/api.py 并验证 /health ready=true。工作区：GWC-Pro-End</pre>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
