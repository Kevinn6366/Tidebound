import { useCallback, useEffect, useState } from 'react';
import type { JSX } from 'react';
import AppCore from './gwc/AppCore.jsx';
import AuthPage from './components/AuthPage';
import ConsolePage from './components/ConsolePage';
import { loadIdentity, logout } from './services/authClient';
import type { AuthUser } from './services/authClient';
import './gwc/utils/theme.js';
import './account.css';

/**
 * 验证账号后挂载原界面，管理员 console 使用独立入口。
 * @returns 登录页、用户界面或当前管理员的运行日志。
 */
export default function App(): JSX.Element {
  const [identity, setIdentity] = useState<{ setup: boolean; user: AuthUser | null } | null>(null);
  const [error, setError] = useState('');
  const [currentPage, setCurrentPage] = useState(window.location.hash.slice(1) || '/main');
  useEffect(() => {
    let cancelled = false;
    void loadIdentity().then(value => { if (!cancelled) setIdentity(value); })
      .catch(failure => { if (!cancelled) setError(failure instanceof Error ? failure.message : '无法读取账号'); });
    const update = (): void => setCurrentPage(window.location.hash.slice(1) || '/main');
    window.addEventListener('hashchange', update);
    return () => { cancelled = true; window.removeEventListener('hashchange', update); };
  }, []);
  const navigate = useCallback((path: string): void => { window.location.hash = path; }, []);
  /** 撤销当前登录，失败时在页面显示可重试的错误。 */
  async function signOut(): Promise<void> {
    try { await logout(); } catch (failure) { setError(failure instanceof Error ? failure.message : '退出失败'); }
  }
  if (!identity) return <main className="account-screen">{error || '正在读取登录状态…'}</main>;
  const user = identity.user;
  if (!user) return <AuthPage setup={identity.setup} />;
  const path = window.location.pathname.replace(/\/$/, '');
  const home = `/app/${user.uid}`;
  if (path === '/app' || path === '/app/index.html') {
    window.location.replace(home);
    return <main className="account-screen">正在进入对话…</main>;
  }
  if (path !== home && path !== `${home}/console`) return <main className="account-screen">无权访问该用户</main>;
  if (path.endsWith('/console')) return user.role === 'admin' ? <ConsolePage user={user} /> : <main className="account-screen">仅管理员可访问</main>;
  return <><AppCore router={{ currentPage, navigate }} /><nav className="account-toolbar">
    <span>{user.username} · {user.uid}</span>
    {user.role === 'admin' && <a href={`${home}/console`}>Console</a>}
    <button onClick={() => { void signOut(); }}>退出登录</button>
    {error && <span role="alert">{error}</span>}
  </nav></>;
}
