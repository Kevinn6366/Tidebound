import { useEffect, useState } from 'react';
import type { JSX } from 'react';
import { debugLoginSetting } from '../services/authClient';

/**
 * 管理员开发免密码登录开关。
 * @param props - 管理员身份。
 * @param props.uid - 已登录管理员 UID。
 * @returns 调试开关与状态说明。
 */
export default function ConsoleDebugLogin({ uid }: { uid: string }): JSX.Element {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    debugLoginSetting(uid).then(value => { if (active) setEnabled(value); })
      .catch((failure: unknown) => { if (active) setError(failure instanceof Error ? failure.message : '读取失败'); });
    return () => { active = false; };
  }, [uid]);

  /** 切换后端调试状态，失败时保留原开关。@returns 切换处理完成。 */
  async function toggle(): Promise<void> {
    setBusy(true); setError('');
    try { setEnabled(await debugLoginSetting(uid, !enabled)); }
    catch (failure) { setError(failure instanceof Error ? failure.message : '切换失败'); }
    finally { setBusy(false); }
  }

  return <section className="console-view-options" aria-label="登录调试">
    <h2>登录调试</h2>
    <p>开启后，知道用户名即可进入该账号；不存在则创建普通账号。仅开发模式可用，开关会保存，重启后保持。</p>
    <p>关闭会撤销免密码登录会话。自动创建的调试账号没有可用密码，仅能在此模式下登录。</p>
    <button disabled={busy || enabled === null} aria-pressed={enabled === true} onClick={toggle}>
      {enabled ? '恢复密码登录' : '取消密码登录（调试）'}
    </button>
    {error && <p role="alert">{error}</p>}
  </section>;
}
