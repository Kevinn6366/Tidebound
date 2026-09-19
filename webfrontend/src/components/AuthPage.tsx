import { useEffect, useState } from 'react';
import type { FormEvent, JSX } from 'react';
import { authenticate, debugLoginSetting } from '../services/authClient';

/**
 * 显示首次管理员初始化、登录和普通用户注册表单。
 * @param props - 首次启动状态。
 * @param props.setup - 是否必须先初始化管理员。
 * @param props.passwordlessDebug - 服务端是否开启用户名调试登录。
 * @returns 账号表单。
 */
export default function AuthPage({ setup, passwordlessDebug = false }: { setup: boolean; passwordlessDebug?: boolean }): JSX.Element {
  const [mode, setMode] = useState<'login' | 'register' | 'setup'>(setup ? 'setup' : 'login');
  const [username, setUsername] = useState(setup ? 'Admin' : '');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [debugEnabled, setDebugEnabled] = useState(passwordlessDebug);
  useEffect(() => {
    let active = true;
    let pending = false;
    /** 同步其他页面切换的登录方式，避免旧页面继续要求密码。 */
    async function refresh(): Promise<void> {
      if (pending) return;
      pending = true;
      try {
        const enabled = await debugLoginSetting('');
        if (active) setDebugEnabled(enabled);
      } catch (failure) {
        if (active) setError(failure instanceof Error ? failure.message : '读取登录方式失败');
      } finally { pending = false; }
    }
    void refresh();
    const timer = setInterval(() => { void refresh(); }, 3000);
    window.addEventListener('focus', refresh);
    return () => { active = false; clearInterval(timer); window.removeEventListener('focus', refresh); };
  }, []);
  const debugLogin = mode === 'login' && debugEnabled;
  const title = mode === 'setup' ? '初始化管理员' : mode === 'register' ? '注册用户' : '登录';

  /**
   * 提交凭据并跳转到服务端分配的用户入口。
   * @param event - 表单提交事件。
   * @returns 请求处理完成。
   */
  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault(); setBusy(true); setError('');
    try {
      const enabled = mode === 'login' && await debugLoginSetting('');
      if (mode === 'login') setDebugEnabled(enabled);
      if (mode === 'login' && !enabled && !password) throw new Error('免密码调试已关闭，请输入密码。');
      const user = await authenticate(enabled ? 'debug-login' : mode, username.trim(), password);
      window.location.assign(`/app/${user.uid}`);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '登录失败');
    } finally { setBusy(false); }
  }

  return <main className="account-screen"><form className="account-card" onSubmit={submit}>
    <p className="account-brand">汐伴 · TIDEBOUND</p>
    <h1>{title}</h1>
    <p>{mode === 'setup' ? '设置首个管理员账号，用户编号为 uid-00000001。' : '登录后继续对话。'}</p>
    <label>用户名<input autoComplete="username" minLength={2} maxLength={64} required
      value={username} onChange={event => setUsername(event.target.value)} /></label>
    {debugLogin && <p role="status">免密码调试已开启：只需用户名，不存在则自动创建普通账号。</p>}
    {!debugLogin && <label>密码<input type="password" autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
      minLength={8} maxLength={256} required placeholder="至少 8 个字符"
      value={password} onChange={event => setPassword(event.target.value)} /></label>}
    {error && <p role="alert" className="account-error">{error}</p>}
    <button type="submit" disabled={busy}>{busy ? '请稍候…' : title}</button>
    {!setup && <button type="button" className="account-secondary" disabled={busy}
      onClick={() => { setMode(mode === 'login' ? 'register' : 'login'); setError(''); }}>
      {mode === 'login' ? '注册新用户' : '已有账号，返回登录'}</button>}
  </form></main>;
}
