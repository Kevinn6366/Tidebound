import { useState, type JSX } from 'react';
import { compactContext } from '../services/chatClient';
import ContextBudgetSettings from './ContextBudgetSettings';

/**
 * 展示管理员专用的悬浮调试工具仓。
 * @param props - 重置状态和已连接服务端的操作。
 * @param props.resetting - 是否正在清空上下文。
 * @param props.disabled - 提交尚未确认时禁止重置，避免请求先后次序不明。
 * @param props.onReset - 清空当前账号有效上下文的入口。
 * @returns 半透明侧边工具仓，包含主动压缩、清空上下文和预算调整。
 */
export default function DevToolbox({ resetting, disabled, onReset }: {
  resetting: boolean;
  disabled: boolean;
  onReset: () => Promise<void>;
}): JSX.Element {
  const [compacting, setCompacting] = useState(false);
  const [feedback, setFeedback] = useState('');
  const [error, setError] = useState('');

  /** 主动运行压缩工作流，展示等待、预算结果或可重试错误，不插入聊天消息。 */
  async function handleCompact(): Promise<void> {
    setCompacting(true);
    setFeedback('');
    setError('');
    try {
      const usage = await compactContext();
      const used = (usage.input_used ?? 0) + usage.output_reserved + usage.format_margin;
      setFeedback(`整理完成，当前占用约 ${Math.round(used / usage.total * 100)}%。`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '整理失败，请重试。');
    } finally {
      setCompacting(false);
    }
  }

  return <aside className="dev-toolbox" aria-label="Dev 工具箱">
    <header><span className="dev-toolbox-dot" /><h2>Dev 工具箱</h2></header>
    <button disabled={disabled || resetting} onClick={() => { void onReset(); }}>
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
        <path d="M4 10a8 8 0 1 1 1 7M4 4v6h6" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      {resetting ? '正在清空…' : '清空上下文'}
    </button>
    <button disabled={disabled || resetting || compacting} onClick={() => { void handleCompact(); }}>
      {compacting ? '正在整理上下文…' : '主动压缩上下文'}
    </button>
    {compacting && <p role="status">正在整理上下文…</p>}
    {feedback && <p role="status">{feedback}</p>}
    {error && <p role="alert">{error}</p>}
    <ContextBudgetSettings />
  </aside>;
}
