import { useState } from 'react';
import type { FormEvent, JSX } from 'react';
import { authenticate } from '../services/authClient';

/**
 * 显示首次管理员初始化、登录和普通用户注册表单。
 * @param props - 首次启动状态。
 * @param props.setup - 是否必须先初始化管理员。
 * @returns 账号表单。
 */
export default function AuthPage({ setup }: { setup: boolean }): JSX.Element {
  const [mode, setMode] = useState<'login' | 'register' | 'setup'>(setup ? 'setup' : 'login');
  const [username, setUsername] = useState(setup ? 'Admin' : '');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const title = mode === 'setup' ? '初始化管理员' : mode === 'register' ? '注册用户' : '登录';

  /**
   * 提交凭据并跳转到服务端分配的用户入口。
   * @param event - 表单提交事件。
   * @returns 请求处理完成。
   */
  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault(); setBusy(true); setError('');
    try {
      const user = await authenticate(mode, username.trim(), password);
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
    <label>密码<input type="password" autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
      minLength={8} maxLength={256} required placeholder="至少 8 个字符"
      value={password} onChange={event => setPassword(event.target.value)} /></label>
    {error && <p role="alert" className="account-error">{error}</p>}
    <button type="submit" disabled={busy}>{busy ? '请稍候…' : title}</button>
    {!setup && <button type="button" className="account-secondary" disabled={busy}
      onClick={() => { setMode(mode === 'login' ? 'register' : 'login'); setError(''); }}>
      {mode === 'login' ? '注册新用户' : '已有账号，返回登录'}</button>}
  </form></main>;
}
