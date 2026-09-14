import { useEffect, useRef, useState } from 'react';
import type { JSX } from 'react';
import type { AuthUser } from '../services/authClient';
import { loadConsoleLog } from '../services/consoleClient';
import type { ConsoleLog } from '../services/consoleClient';

/**
 * 持续显示固定日志末尾 100 行，管理员可暂停滚动查看内容。
 * @param props - 已验证的账号身份。
 * @param props.user - 当前管理员。
 * @returns 日志控制台页面。
 */
export default function ConsolePage({ user }: { user: AuthUser }): JSX.Element {
  const [log, setLog] = useState<ConsoleLog | null>(null);
  const [error, setError] = useState('');
  const [follow, setFollow] = useState(true);
  const output = useRef<HTMLPreElement>(null);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    /** 串行读取文件尾部；页面卸载后停止刷新。 */
    async function refresh(): Promise<void> {
      try {
        const result = await loadConsoleLog(user.uid, controller.signal);
        if (!controller.signal.aborted) { setLog(result); setError(''); }
      } catch (failure) {
        if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : '日志读取失败');
      } finally {
        if (!controller.signal.aborted) timer = setTimeout(refresh, 1000);
      }
    }
    void refresh();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [user.uid]);
  useEffect(() => {
    if (follow && output.current) output.current.scrollTop = output.current.scrollHeight;
  }, [log?.content, follow]);

  return <main className="console-screen">
    <header><div><p className="account-brand">TIDEBOUND / CONSOLE</p><h1>LLM 运行日志</h1>
      <p>{user.username} · {user.uid} · 管理员</p></div><a href={`/app/${user.uid}`}>返回对话</a></header>
    <div className="console-controls"><p>agent-debug.log · 最近 100 行 · 每秒刷新</p>
      <label><input type="checkbox" checked={follow} onChange={event => setFollow(event.target.checked)} /> 自动滚动</label></div>
    {error && <p role="alert" className="account-error">{error}</p>}
    {log?.truncated && <p>日志尾部超过单次读取上限，仅展示最近 256 KiB。</p>}
    <pre ref={output} className="console-output" aria-label="运行日志">{log === null ? '正在读取日志…'
      : !log.exists ? '日志文件尚未创建，等待服务输出…' : log.content || '日志文件为空，等待服务输出…'}</pre>
  </main>;
}
