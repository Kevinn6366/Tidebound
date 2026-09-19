import { useEffect, useState } from 'react';
import type { JSX } from 'react';
import { loadModelChannels, selectModelChannel } from '../services/modelChannelsClient';
import type { ChannelId, ModelChannels } from '../services/modelChannelsClient';

/**
 * 展示主聊天渠道并允许管理员一键切换。
 * @param props - 当前账号属性。
 * @param props.uid - 已登录管理员 UID。
 * @returns 渠道选择、配置状态和提交反馈。
 */
export default function ConsoleModelChannels({ uid }: { uid: string }): JSX.Element {
  const [data, setData] = useState<ModelChannels | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [reload, setReload] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setError('');
    loadModelChannels(uid, controller.signal).then(setData).catch((cause: unknown) => {
      if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : '读取渠道失败');
    });
    return () => controller.abort();
  }, [uid, reload]);

  /**
   * 保存选择并以服务端返回值更新页面，失败时保留旧选择。
   * @param channel - 用户点击的目标渠道。
   * @returns 提交和反馈更新结束。
   */
  async function switchChannel(channel: ChannelId): Promise<void> {
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const updated = await selectModelChannel(uid, channel);
      setData(updated);
      setNotice('已切换，从下一轮主聊天生效。');
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : '切换失败');
    } finally {
      setBusy(false);
    }
  }

  return <section aria-label="主聊天模型来源">
    <h2>主聊天模型来源</h2>
    <p>对本服务所有账号的新对话轮次生效，重启后保留。正在回复的对话及欢迎模型保持原配置。</p>
    {error && <p role="alert">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    {!data && !error && <p>正在读取渠道…</p>}
    <div className="console-view-options">
      {data?.channels.map(channel => <div key={channel.id}>
        <h3>{channel.name}</h3>
        <p>{channel.model || '未配置模型'}</p>
        <p>{channel.base_url}</p>
        <button disabled={busy || !channel.ready || data.selected === channel.id}
          aria-pressed={data.selected === channel.id} onClick={() => void switchChannel(channel.id)}>
          {data.selected === channel.id ? '当前使用' : `切换到 ${channel.name}`}
        </button>
        {!channel.ready && <p>未配置：请在后端 .env 填写模型、地址和 API Key，重启后刷新。</p>}
      </div>)}
    </div>
    <button disabled={busy} onClick={() => setReload(value => value + 1)}>刷新渠道状态</button>
  </section>;
}
