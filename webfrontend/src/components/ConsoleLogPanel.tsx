import { useEffect, useRef, useState } from 'react';
import type { JSX } from 'react';
import type { AuthUser } from '../services/authClient';
import { loadConsoleLog } from '../services/consoleClient';
import type { ConsoleLog } from '../services/consoleClient';

/**
 * 将结构化执行事件转换为可定位阶段的文本，不把日志当作 HTML。
 * @param text - 后端有界 JSONL 事件。
 * @param filter - Run、工作流或工具的过滤词。
 * @returns 按时间排列的可读事件。
 */
function formatEvents(text: string, filter: string): string {
  return text.split('\n').filter(line => line && line.toLowerCase().includes(filter.toLowerCase())).map(line => {
    try {
      const item: unknown = JSON.parse(line);
      if (typeof item !== 'object' || item === null) return line;
      const event = item as Record<string, unknown>;
      return `${event.time} [${event.status}] ${event.kind} / ${event.name}\n  Run=${event.run_id || '后台'} · 步骤=${event.step} · 模型=${event.model || '-'}${event.duration_ms === null ? '' : ` · ${event.duration_ms} ms`}${event.error_code ? ` · 错误=${event.error_code}` : ''}`;
    } catch { return line; }
  }).join('\n');
}

/**
 * 串行轮询运行事件，单次超时后自动重试，保留最近成功内容。
 * @param props - 当前身份。
 * @param props.user - 已验证的管理员。
 * @returns 运行事件与原始终端日志查看区。
 */
export default function ConsoleLogPanel({ user }: { user: AuthUser }): JSX.Element {
  const [log, setLog] = useState<ConsoleLog | null>(null);
  const [error, setError] = useState('');
  const [follow, setFollow] = useState(true);
  const [paused, setPaused] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [updated, setUpdated] = useState('');
  const [reading, setReading] = useState(false);
  const [legacy, setLegacy] = useState(false);
  const [filter, setFilter] = useState('');
  const output = useRef<HTMLPreElement>(null);
  useEffect(() => {
    let active = true;
    let controller: AbortController | undefined;
    let timer: ReturnType<typeof setTimeout> | undefined;
    /** 每次请求独立设置超时，避免某次悬挂后永久停止轮询。 */
    async function refresh(): Promise<void> {
      controller = new AbortController();
      const current = controller;
      let timedOut = false;
      const deadline = setTimeout(() => { timedOut = true; current.abort(); }, 8000);
      setReading(true);
      try {
        const result = await loadConsoleLog(user.uid, current.signal);
        if (active) { setLog(result); setError(''); setUpdated(new Date().toLocaleTimeString()); }
      } catch (failure) {
        if (active) setError(timedOut ? '读取超过 8 秒，正在自动重试；保留上次日志。'
          : failure instanceof Error ? failure.message : '日志读取失败');
      } finally {
        clearTimeout(deadline);
        if (active) { setReading(false); if (!paused) timer = setTimeout(refresh, 1500); }
      }
    }
    void refresh();
    return () => { active = false; controller?.abort(); clearTimeout(timer); };
  }, [user.uid, paused, refreshKey]);
  const content = legacy ? log?.content || '' : formatEvents(log?.eventsContent || '', filter);
  useEffect(() => {
    if (follow && output.current) output.current.scrollTop = output.current.scrollHeight;
  }, [content, follow]);

  return <section aria-label="运行日志查看区">
    <div className="console-controls">
      <p>{legacy ? '终端日志 · 最近 100 行' : '执行事件 · 最近 500 条'} · {paused ? '已暂停自动刷新' : '每 1.5 秒刷新'}
        {reading ? ' · 读取中…' : ''}{updated ? ` · 最近成功：${updated}` : ''}</p>
      <button onClick={() => setPaused(value => !value)}>{paused ? '恢复刷新' : '暂停刷新'}</button>
      <button onClick={() => setRefreshKey(value => value + 1)}>立即刷新</button>
      <label><input type="checkbox" checked={follow} onChange={event => setFollow(event.target.checked)} /> 自动滚动</label>
      <label><input type="checkbox" checked={legacy} onChange={event => setLegacy(event.target.checked)} /> 原始终端日志</label>
      {!legacy && <input aria-label="过滤执行日志" placeholder="Run ID / 工具 / 工作流 / failed" value={filter} onChange={event => setFilter(event.target.value)} />}
    </div>
    {error && <p role="alert" className="account-error">{error}</p>}
    {legacy && log?.truncated && <p>仅展示日志尾部，较早内容已省略。</p>}
    <pre ref={output} className="console-output" aria-label="运行日志">{log === null ? '正在读取日志…'
      : content || (filter && !legacy ? '没有匹配的执行事件。' : '暂无日志，等待下一次执行…')}</pre>
  </section>;
}
