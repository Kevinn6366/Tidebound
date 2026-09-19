import { useState } from 'react';
import type { JSX } from 'react';
import type { AuthUser } from '../services/authClient';
import ConsoleRequests from './ConsoleRequests';
import ConsoleLogPanel from './ConsoleLogPanel';
import ConsoleModelChannels from './ConsoleModelChannels';
import ConsoleDebugLogin from './ConsoleDebugLogin';

/**
 * 提供主聊天渠道切换，以及完整 LLM 上下文与运行日志入口。
 * @param props - 已验证的账号信息。
 * @param props.user - 当前管理员。
 * @returns 管理员 console 选择页及所选查看区。
 */
export default function ConsolePage({ user }: { user: AuthUser }): JSX.Element {
  const [view, setView] = useState<'context' | 'log' | null>(null);
  return <main className="console-screen">
    <header><div><p className="account-brand">TIDEBOUND / CONSOLE</p><h1>控制台</h1>
      <p>{user.username} · {user.uid} · 管理员</p></div><a href={`/app/${user.uid}`}>返回对话</a></header>
    <ConsoleModelChannels uid={user.uid} />
    <ConsoleDebugLogin uid={user.uid} />
    <nav className="console-view-options" aria-label="控制台功能">
      <button aria-pressed={view === 'context'} onClick={() => setView('context')}>查看完整 LLM 对话上下文</button>
      <button aria-pressed={view === 'log'} onClick={() => setView('log')}>查看日志</button>
    </nav>
    {view === null && <p className="console-hint">请选择要查看的内容。</p>}
    {view === 'context' && <ConsoleRequests uid={user.uid} />}
    {view === 'log' && <ConsoleLogPanel user={user} />}
  </main>;
}
