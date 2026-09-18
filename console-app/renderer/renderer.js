const { ipcRenderer } = require('electron')

const MAX_LINES = 3000
const panes = {} // id -> { body, dot, status, collapsed, lines: [] }

function esc(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function createPane(svc) {
  const el = document.createElement('div')
  el.className = 'pane'
  el.style.setProperty('--accent', svc.color)
  el.innerHTML = `
    <div class="pane-header">
      <span class="dot"></span>
      <button class="collapse-btn" title="显示/隐藏日志">▾</button>
      <span class="pane-title">${esc(svc.name)}</span>
      <span class="pane-status">已停止</span>
      <div class="pane-actions">
        ${svc.remote ? '<button class="mini start">启动</button>' : ''}
        <button class="mini restart">重启</button>
        <button class="mini stop">停止</button>
        ${svc.remote ? '' : '<button class="mini terminal">独立终端</button>'}
      </div>
    </div>
    <div class="pane-body"></div>
  `
  document.getElementById('panes').appendChild(el)

  const body = el.querySelector('.pane-body')
  const dot = el.querySelector('.dot')
  const status = el.querySelector('.pane-status')
  const collapseBtn = el.querySelector('.collapse-btn')

  panes[svc.id] = { body, dot, status, collapsed: false, lines: [], remote: !!svc.remote }

  el.querySelector('.stop').addEventListener('click', () => ipcRenderer.send('stop-service', svc.id))
  el.querySelector('.restart').addEventListener('click', () => ipcRenderer.send('restart-service', svc.id))
  if (!svc.remote) el.querySelector('.terminal').addEventListener('click', () => ipcRenderer.send('open-terminal', svc.id))
  if (svc.remote) el.querySelector('.start').addEventListener('click', () => ipcRenderer.send('start-service', svc.id))

  collapseBtn.addEventListener('click', () => {
    const p = panes[svc.id]
    p.collapsed = !p.collapsed
    el.classList.toggle('collapsed', p.collapsed)
    collapseBtn.textContent = p.collapsed ? '▸' : '▾'
  })
}

function appendLine(id, line, isErr) {
  const p = panes[id]
  if (!p) return
  const div = document.createElement('div')
  div.className = 'log-line' + (isErr ? ' err' : '')
  div.textContent = line
  p.body.appendChild(div)
  p.lines.push(div)

  while (p.lines.length > MAX_LINES) {
    const first = p.lines.shift()
    if (first && first.parentNode) first.parentNode.removeChild(first)
  }

  const nearBottom = p.body.scrollHeight - p.body.scrollTop - p.body.clientHeight < 60
  if (nearBottom) p.body.scrollTop = p.body.scrollHeight
}

// 远程面板（TTS）：全量替换展示最近日志，避免轮询重复累加
function replaceLines(id, lines) {
  const p = panes[id]
  if (!p) return
  p.body.textContent = ''
  p.lines = []
  for (const line of lines) {
    const div = document.createElement('div')
    div.className = 'log-line'
    div.textContent = line
    p.body.appendChild(div)
    p.lines.push(div)
  }
  p.body.scrollTop = p.body.scrollHeight
}

function setStatus(id, running) {
  const p = panes[id]
  if (!p) return
  p.dot.classList.toggle('on', running)
  p.status.textContent = running ? '运行中' : '已停止'
  p.status.classList.toggle('running', running)
}

ipcRenderer.on('service', (e, msg) => {
  const { id, type } = msg
  if (!panes[id]) return
  if (type === 'log') appendLine(id, msg.line, msg.err)
  else if (type === 'logBatch') replaceLines(id, msg.lines || [])
  else if (type === 'status') setStatus(id, msg.running)
  else if (type === 'exit') {
    setStatus(id, false)
    appendLine(id, `> 进程退出 (code=${msg.code}, signal=${msg.signal || 'none'})`, true)
  }
})

// 远程 TTS 面板独立轮询（每 2.5s 通过主进程拉后端状态+日志）
function startRemoteTimers() {
  setInterval(() => {
    for (const id in panes) {
      if (panes[id].remote) ipcRenderer.send('remote-poll', id)
    }
  }, 2500)
}

async function init() {
  const services = await ipcRenderer.invoke('get-services')
  for (const svc of services) createPane(svc)
  startRemoteTimers()
}

document.getElementById('btn-start-all').addEventListener('click', () => ipcRenderer.send('start-all'))
document.getElementById('btn-stop-all').addEventListener('click', () => ipcRenderer.send('stop-all'))

init()