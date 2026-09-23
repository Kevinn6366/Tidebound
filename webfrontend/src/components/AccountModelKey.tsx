import { useEffect, useState } from 'react';
import { frontendFetch } from '../services/frontendFetch';

type CredentialStatus = {
  provider: 'siliconflow';
  configured: boolean;
  model: string;
  base_url: string;
};

/** 仅显示账号的凭据状态；密钥仅在用户输入后发送给服务端。 */
export default function AccountModelKey(): React.JSX.Element {
  const [status, setStatus] = useState<CredentialStatus | null>(null);
  const [apiKey, setApiKey] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');

  useEffect(() => {
    let active = true;
    frontendFetch('/api/model-credential')
      .then((response) => response.json() as Promise<CredentialStatus>)
      .then((value) => { if (active) setStatus(value); })
      .catch(() => { if (active) setMessage('读取配置失败，请刷新页面重试。'); });
    return () => { active = false; };
  }, []);

  /** 保存或删除当前登录账号的密钥，并用服务端状态更新界面。 */
  async function changeCredential(method: 'PUT' | 'DELETE'): Promise<void> {
    setBusy(true);
    setMessage('');
    try {
      const response = await frontendFetch('/api/model-credential', {
        method,
        headers: method === 'PUT' ? { 'Content-Type': 'application/json' } : undefined,
        body: method === 'PUT' ? JSON.stringify({ api_key: apiKey.trim() }) : undefined,
      });
      setStatus(await response.json() as CredentialStatus);
      setApiKey('');
      setMessage(method === 'PUT' ? '已保存本账号的 API Key。' : '已删除本账号的 API Key。');
    } catch {
      setMessage('操作失败，请检查密钥长度或稍后重试。');
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="bg-white/60 p-6 rounded-xl border border-[#e6d5b8] shadow-sm space-y-4">
      <p className="text-sm text-[#4a4036]">默认服务商：硅基流动。每个账号独立配置，密钥只保存在服务端。</p>
      <p className="text-xs text-[#7a6b5d]">模型：{status?.model ?? '加载中…'} · 地址：{status?.base_url ?? '加载中…'}</p>
      <p className="text-sm font-bold text-[#4a4036]" role="status">
        {status ? (status.configured ? '本账号已配置 API Key' : '本账号尚未配置 API Key') : '正在读取配置…'}
      </p>
      <label className="block text-sm font-bold text-[#ba3f42]" htmlFor="account-model-api-key">硅基流动 API Key</label>
      <input
        id="account-model-api-key"
        type="password"
        autoComplete="off"
        value={apiKey}
        onChange={(event) => setApiKey(event.target.value)}
        placeholder={status?.configured ? '输入新 Key 以替换现有配置' : '输入本账号的 API Key'}
        className="w-full bg-white border border-[#d9c5b2] text-[#4a4036] rounded-md px-4 py-2 outline-none focus:border-[#ba3f42]"
      />
      <div className="flex gap-3">
        <button type="button" disabled={busy || apiKey.trim().length < 8} onClick={() => void changeCredential('PUT')} className="px-4 py-2 bg-[#4fa0d8] disabled:opacity-50 text-white font-bold rounded-lg">保存 Key</button>
        {status?.configured && <button type="button" disabled={busy} onClick={() => void changeCredential('DELETE')} className="px-4 py-2 bg-red-500 disabled:opacity-50 text-white font-bold rounded-lg">删除 Key</button>}
      </div>
      {message && <p role="alert" className="text-sm text-[#7a6b5d]">{message}</p>}
    </section>
  );
}
