import { useEffect, useRef, useState } from 'react';
import type { JSX } from 'react';
import { Activity, ArrowUpRight, ChevronRight, Cpu, LayoutDashboard, LogOut, MessagesSquare, ShieldCheck, Waves } from 'lucide-react';
import { logout } from '../services/authClient';
import type { AuthUser } from '../services/authClient';
import ConsoleRequests from './ConsoleRequests';
import ConsoleLogPanel from './ConsoleLogPanel';
import ConsoleModelChannels from './ConsoleModelChannels';
import ConsoleDebugLogin from './ConsoleDebugLogin';
import ConsoleOverview from './ConsoleOverview';
import '../console.css';

const pages = [
  { id: 'overview', title: '概览', icon: LayoutDashboard, description: '对话、模型与调试入口，一目了然。' },
  { id: 'context', title: '对话上下文', icon: MessagesSquare, description: '沿着每一轮对话，检查模型真正收到的内容。', label: '查看完整 LLM 对话上下文' },
  { id: 'log', title: '运行日志', icon: Activity, description: '追踪模型、工作流和工具的每一步执行。', label: '查看日志' },
  { id: 'models', title: '模型渠道', icon: Cpu, description: '管理主聊天模型的来源与配置。' },
  { id: 'settings', title: '登录调试', icon: ShieldCheck, description: '查看当前身份，管理开发环境的登录方式。' },
] as const;

/**
 * 提供与对话前端一致的管理后台外壳，按需挂载各功能页。
 * @param props - 已验证的身份。
 * @param props.user - 当前管理员账号。
 * @returns 带导航、面包屑和功能内容的管理后台。
 */
export default function ConsolePage({ user }: { user: AuthUser }): JSX.Element {
  const [route, setRoute] = useState(window.location.hash);
  const workspace = useRef<HTMLDivElement>(null);
  const shell = useRef<HTMLDivElement>(null);
  const view = pages.find(item => `#${item.id}` === route.split('?')[0])?.id ?? 'overview';
  const [error, setError] = useState('');
  const [signingOut, setSigningOut] = useState(false);
  useEffect(() => {
    /** 响应页面导航并复位内容滚动，跳读链接只移动焦点。@returns 导航同步完成。 */
    const change = (): void => {
      if (window.location.hash !== '#console-content') {
        setRoute(window.location.hash);
        workspace.current?.scrollTo(0, 0);
        shell.current?.scrollTo(0, 0);
      }
    };
    window.addEventListener('hashchange', change);
    return () => window.removeEventListener('hashchange', change);
  }, []);
  const page = pages.find(item => item.id === view)!;

  /** 结束管理员会话，失败时展示可重试的错误。@returns 注销处理完成。 */
  async function signOut(): Promise<void> {
    setSigningOut(true);
    try { await logout(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : '退出失败，请重试'); setSigningOut(false); }
  }

  return <div ref={shell} className="console-screen console-shell">
    <a className="console-skip" href="#console-content">跳到主要内容</a>
    <aside className="console-sidebar">
      <a className="console-brand" href="#overview" aria-label="汐伴管理后台概览">
        <span className="console-brand-mark"><Waves size={25} /></span>
        <span><strong>汐伴</strong><small>TIDEBOUND CONSOLE</small></span>
      </a>
      <p className="console-nav-label">工作空间</p>
      <nav aria-label="控制台功能">
        {pages.map(item => <a key={item.id} href={`#${item.id}`} aria-current={view === item.id ? 'page' : undefined}
          aria-label={'label' in item ? item.label : item.title}>
          <item.icon size={18} aria-hidden="true" /><span>{item.title}</span>
          {view === item.id && <ChevronRight size={14} className="console-nav-chevron" />}
        </a>)}
      </nav>
      <div className="console-sidebar-bottom">
        <div className="console-profile"><span className="console-avatar">{user.username.slice(0, 1).toUpperCase()}</span>
          <div><strong>{user.username}</strong><small>管理员</small></div></div>
        <button onClick={() => void signOut()} disabled={signingOut}><LogOut size={16} />{signingOut ? '正在退出…' : '退出登录'}</button>
      </div>
    </aside>
    <div ref={workspace} className="console-workspace">
      <header className="console-topbar"><div className="console-breadcrumb"><span>管理后台</span><ChevronRight size={14} /><strong>{page.title}</strong></div>
        <a href={`/app/${user.uid}`} className="console-return">返回对话 <ArrowUpRight size={16} /></a></header>
      <main id="console-content" className="console-content" tabIndex={-1}>
        <div className="console-page-heading"><div><p className="console-eyebrow">TIDEBOUND / WORKSPACE</p><h1>{page.title}</h1><p>{page.description}</p></div>
          <span className="console-badge"><ShieldCheck size={14} />管理员空间</span></div>
        {error && <p role="alert" className="account-error">{error}</p>}
        {view === 'overview' && <ConsoleOverview uid={user.uid} />}
        {view === 'context' && <ConsoleRequests key={route} uid={user.uid} />}
        {view === 'log' && <ConsoleLogPanel user={user} />}
        {view === 'models' && <ConsoleModelChannels uid={user.uid} />}
        {view === 'settings' && <>
          <section className="console-panel console-identity"><h2>当前账号</h2><dl><div><dt>用户名</dt><dd>{user.username}</dd></div><div><dt>账号编号</dt><dd>{user.uid}</dd></div><div><dt>权限</dt><dd>管理员</dd></div></dl></section>
          <ConsoleDebugLogin uid={user.uid} /></>}
        <footer className="console-footer"><span>汐伴 · Tidebound</span><span>陪伴在前台，掌握在这里。</span></footer>
      </main>
    </div>
  </div>;
}
