// ============================================================
// GWC 全栈控制台（窗口合并器）
//
// 把原本每次启动都要开启的多个 cmd 窗口（后端 / 前端 / 桌宠 / OpenCode）
// 合并进一个窗口，每个服务一个独立、隔离的日志面板，实时流式显示。
//
// - 后端先启动，轮询 5201 端口就绪后再拉起其余服务（与旧 bat 一致）
// - 每个子进程 stdout/stderr 单独管道，按行拆分成事件推给渲染进程
// - 关闭本窗口会连同子进程树一起结束（taskkill /T）
// ============================================================

const { app, BrowserWindow, ipcMain, shell } = require('electron')
const { spawn, exec } = require('child_process')
const path = require('path')
const fs = require('fs')
const net = require('net')
const http = require('http')

const ROOT = path.join(__dirname, '..')
const BACKEND_PORT = 5201
const BACKEND_BASE = `http://127.0.0.1:${BACKEND_PORT}`

let mainWindow = null
const children = new Map() // id -> ChildProcess

// ============================================================
// 服务定义
// ============================================================
const SERVICES = [
  {
    id: 'backend',
    name: '后端 Backend',
    color: '#5ab4ed',
    cwd: path.join(ROOT, 'backend'),
    command: path.join(ROOT, 'backend', 'runtime', 'python.exe'),
    args: ['main.py'],
    env: { PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1' },
    waitPort: BACKEND_PORT,
  },
  {
    id: 'frontend',
    name: '前端 Frontend',
    color: '#4ade80',
    cwd: path.join(ROOT, 'desktop-app'),
    command: path.join(ROOT, 'desktop-app', 'node_modules', 'electron', 'dist', 'electron.exe'),
    args: ['.'],
  },
  {
    id: 'deskpet',
    name: '桌宠 DeskPet',
    color: '#f472b6',
    cwd: path.join(ROOT, 'electron-app'),
    command: path.join(ROOT, 'electron-app', 'node_modules', 'electron', 'dist', 'electron.exe'),
    args: ['.'],
  },
  {
    id: 'opencode',
    name: 'OpenCode',
    color: '#facc15',
    cwd: ROOT,
    command: 'opencode',
    args: [],
    shell: true,
    tui: true, // 交互式 TUI，无法通过管道显示，需在独立终端运行
  },
  {
    id: 'tts_sovits',
    name: 'TTS (GPT-SoVITS)',
    color: '#f59e0b',
    remote: {
      status: '/api/tts/status',
      log: '/api/tts/logs?engine=sovits',
      start: '/api/tts/start',
      stop: '/api/tts/stop',
    },
  },
  {
    id: 'tts_qwen',
    name: 'TTS (Qwen3)',
    color: '#a78bfa',
    remote: {
      status: '/api/tts/qwen/status',
      log: '/api/tts/qwen/logs',
      start: '/api/tts/qwen/start',
      stop: '/api/tts/qwen/stop',
      install: '/api/tts/qwen/install',
    },
  },
]

// ============================================================
// 工具函数
// ============================================================
function send(id, msg) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('service', { id, ...msg })
  }
}

function pipeLines(stream, id, isErr) {
  let buf = ''
  stream.setEncoding('utf8')
  stream.on('data', (chunk) => {
    buf += chunk
    let idx
    while ((idx = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, idx).replace(/\r$/, '')
      buf = buf.slice(idx + 1)
      if (line.length) send(id, { type: 'log', line, err: isErr })
    }
  })
  stream.on('end', () => {
    if (buf.length) send(id, { type: 'log', line: buf, err: isErr })
  })
}

function waitForPort(port, timeoutMs = 90000) {
  return new Promise((resolve) => {
    const start = Date.now()
    const attempt = () => {
      const socket = net.connect(port, '127.0.0.1')
      socket.once('connect', () => { socket.destroy(); resolve(true) })
      socket.once('error', () => {
        socket.destroy()
        if (Date.now() - start > timeoutMs) resolve(false)
        else setTimeout(attempt, 1000)
      })
    }
    attempt()
  })
}

// ============================================================
// 远程服务（TTS 由 backend 管理，控制台通过 HTTP 远程控制 + 拉日志）
// ============================================================
function httpJson(method, apiPath, body) {
  return new Promise((resolve) => {
    const data = body ? JSON.stringify(body) : null
    const req = http.request(BACKEND_BASE + apiPath, {
      method,
      headers: data ? { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) } : {},
    }, (res) => {
      let buf = ''
      res.setEncoding('utf8')
      res.on('data', (c) => { buf += c })
      res.on('end', () => {
        try { resolve(JSON.parse(buf)) } catch (e) { resolve({ ok: false, msg: buf.slice(0, 200) }) }
      })
    })
    req.on('error', (e) => resolve({ ok: false, msg: '后端不可达: ' + e.message }))
    if (data) req.write(data)
    req.end()
  })
}

async function pollRemote(svc) {
  // 状态
  try {
    const st = await httpJson('GET', svc.remote.status)
    const running = !!(st && st.running)
    send(svc.id, { type: 'status', running })
    if (!running && st && st.msg && st.msg.includes('need_model')) {
      send(svc.id, { type: 'log', line: `⚠ ${st.msg}`, err: true })
    }
  } catch (e) {}
  // 日志（附加式拉取）
  try {
    const lg = await httpJson('GET', svc.remote.log)
    if (lg && Array.isArray(lg.lines)) {
      send(svc.id, { type: 'logBatch', lines: lg.lines })
    }
  } catch (e) {}
}

function startRemotePolling(svc) {
  setInterval(() => pollRemote(svc), 2000)
}

function killTree(pid) {
  if (!pid) return
  if (process.platform === 'win32') {
    exec(`taskkill /F /T /PID ${pid}`, () => {})
  } else {
    try { process.kill(pid, 'SIGTERM') } catch (e) {}
  }
}

function killAll() {
  for (const [, child] of children) {
    killTree(child.pid)
  }
  children.clear()
}

function shouldSkipOpencode() {
  try {
    const p = path.join(ROOT, 'userdata', 'launcher_config.json')
    if (fs.existsSync(p)) {
      const cfg = JSON.parse(fs.readFileSync(p, 'utf-8'))
      if (cfg && cfg.disableOpencodeAutostart === true) return true
    }
  } catch (e) {}
  return false
}

// ============================================================
// 服务启停
// ============================================================
function spawnService(svc) {
  return new Promise((resolve) => {
    const exists = fs.existsSync(svc.command)
    if (!svc.shell && !exists) {
      send(svc.id, { type: 'log', line: `[启动失败] 未找到可执行文件: ${svc.command}`, err: true })
      send(svc.id, { type: 'exit', code: -1, signal: 'ENOENT' })
      return resolve(null)
    }

    const opts = {
      cwd: svc.cwd,
      env: { ...process.env, ...(svc.env || {}) },
      shell: !!svc.shell,
    }
    let child
    try {
      child = spawn(svc.command, svc.args, opts)
    } catch (e) {
      send(svc.id, { type: 'log', line: `[启动失败] ${e.message}`, err: true })
      send(svc.id, { type: 'exit', code: -1, signal: 'SPAWN_ERR' })
      return resolve(null)
    }

    children.set(svc.id, child)
    send(svc.id, { type: 'status', running: true })
    send(svc.id, { type: 'log', line: `> ${svc.command} ${svc.args.join(' ')}` })

    pipeLines(child.stdout, svc.id, false)
    pipeLines(child.stderr, svc.id, true)

    child.on('error', (e) => {
      send(svc.id, { type: 'log', line: `[错误] ${e.message}`, err: true })
    })
    child.on('exit', (code, signal) => {
      children.delete(svc.id)
      send(svc.id, { type: 'status', running: false })
      send(svc.id, { type: 'exit', code, signal })
    })
    resolve(child)
  })
}

function stopService(id) {
  const svc = SERVICES.find((s) => s.id === id)
  if (svc && svc.remote) {
    httpJson('POST', svc.remote.stop).then((r) => {
      send(id, { type: 'log', line: r && r.ok ? `> 已发送停止指令` : `> ${(r && r.msg) || '停止失败'}`, err: !(r && r.ok) })
    })
    return
  }
  const child = children.get(id)
  if (child) killTree(child.pid)
}

function restartService(id) {
  const svc = SERVICES.find((s) => s.id === id)
  if (svc && svc.remote) {
    stopService(id)
    setTimeout(() => {
      httpJson('POST', svc.remote.start).then((r) => {
        send(id, { type: 'log', line: r && r.ok ? `> 已发送启动指令` : `> ${(r && r.msg) || '启动失败'}`, err: !(r && r.ok) })
      })
    }, 800)
    return
  }
  stopService(id)
  setTimeout(() => spawnService(svc), 1200)
}

function openTerminalFor(svc) {
  const cmd = svc.shell
    ? `start "GWC ${svc.name}" cmd /k "cd /d "${svc.cwd}" && ${svc.command}"`
    : `start "GWC ${svc.name}" cmd /k "cd /d "${svc.cwd}" && "${svc.command}" ${svc.args.join(' ')}"`
  exec(cmd, (err) => {
    if (err) send(svc.id, { type: 'log', line: `[独立终端启动失败] ${err.message}`, err: true })
  })
}

async function startAll() {
  for (const svc of SERVICES) {
    if (children.has(svc.id)) continue // 已运行
    if (svc.remote) {
      // 远程服务（TTS 由 backend 管理）：只启动轮询，不手动拉起
      send(svc.id, { type: 'log', line: '> TTS 由后端管理，此处仅显示状态与日志（可在下方用按钮启停）', err: false })
      startRemotePolling(svc)
      pollRemote(svc)
      continue
    }
    if (svc.id === 'opencode' && shouldSkipOpencode()) {
      send(svc.id, { type: 'log', line: '> 已在设置中禁用 OpenCode 自动启动，跳过', err: false })
      continue
    }
    if (svc.tui) {
      // 交互式 TUI 无法通过管道显示，改在独立终端窗口启动
      send(svc.id, { type: 'log', line: '> OpenCode 为交互式终端，已在独立窗口启动', err: false })
      openTerminalFor(svc)
      continue
    }
    if (svc.waitPort) {
      // 后端：先启动并等待端口就绪
      await spawnService(svc)
      const ok = await waitForPort(svc.waitPort)
      send(svc.id, { type: 'log', line: ok ? '> 端口已就绪' : '> 等待端口超时，继续启动其余服务', err: !ok })
    } else {
      await spawnService(svc)
    }
  }
}

// ============================================================
// IPC
// ============================================================
ipcMain.handle('get-services', () => SERVICES.map((s) => ({ id: s.id, name: s.name, color: s.color, remote: !!s.remote })))
ipcMain.on('start-all', () => { startAll() })
ipcMain.on('stop-all', () => { killAll() })
ipcMain.on('stop-service', (e, id) => { stopService(id) })
ipcMain.on('restart-service', (e, id) => { restartService(id) })
ipcMain.on('start-service', (e, id) => {
  const svc = SERVICES.find((s) => s.id === id)
  if (!svc) return
  if (svc.remote) {
    httpJson('POST', svc.remote.start).then((r) => {
      send(id, { type: 'log', line: r && r.ok ? `> 已发送启动指令` : `> ${(r && r.msg) || '启动失败'}`, err: !(r && r.ok) })
    })
  } else if (!children.has(id)) {
    spawnService(svc)
  }
})
ipcMain.on('open-terminal', (e, id) => {
  const svc = SERVICES.find((s) => s.id === id)
  if (!svc) return
  openTerminalFor(svc)
})
ipcMain.on('remote-poll', (e, id) => {
  const svc = SERVICES.find((s) => s.id === id)
  if (svc && svc.remote) pollRemote(svc)
})

// ============================================================
// 窗口
// ============================================================
function createWindow() {
  const win = new BrowserWindow({
    width: 1200,
    height: 860,
    minWidth: 800,
    minHeight: 600,
    title: 'GWC Console',
    backgroundColor: '#0b1220',
    autoHideMenuBar: true,
    webPreferences: { nodeIntegration: true, contextIsolation: false },
  })
  win.loadFile(path.join(__dirname, 'renderer', 'index.html'))
  win.on('closed', () => { mainWindow = null })
  return win
}

// ============================================================
// 生命周期（单实例锁）
// ============================================================
const gotLock = app.requestSingleInstanceLock()
if (!gotLock) {
  app.quit()
} else {
  app.on('second-instance', () => {
    if (mainWindow) { mainWindow.show(); mainWindow.focus() }
  })

  app.whenReady().then(() => {
    mainWindow = createWindow()
    mainWindow.webContents.on('did-finish-load', () => { startAll() })
  })

  app.on('window-all-closed', () => {
    app.quit()
  })

  app.on('will-quit', () => {
    killAll()
  })
}
