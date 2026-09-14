import { useCallback, useEffect, useRef, useState } from 'react';
import { loadChatSession, readChatRun, stopChatRun, submitChatMessage, type ChatMessageInput, type SessionView } from '../services/chatClient';

const EMPTY: SessionView = { character: 'atri', character_name: '亚托莉', messages: [], active_run: null, tool_runs: [] };

/**
 * 维护服务端会话的展示副本，重连只查询，不重放用户输入。
 * @returns 固定角色的历史、忙碌状态、发送与显式停止入口。
 */
export function useAgentChat(): {
  session: SessionView; ready: boolean; error: string; busy: boolean;
  send: (input: Omit<ChatMessageInput, 'run_id'>) => Promise<void>;
  stop: () => Promise<void>;
} {
  const [session, setSession] = useState<SessionView>(EMPTY);
  const [pending, setPending] = useState(false);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState('');
  const runId = useRef<string | null>(null);
  const sending = useRef(false);
  const requestSequence = useRef(0);
  const refresh = useCallback(async () => {
    const sequence = ++requestSequence.current;
    const snapshot = await loadChatSession();
    if (sequence === requestSequence.current) {
      setSession(previous => JSON.stringify(previous) === JSON.stringify(snapshot) ? previous : snapshot);
      setReady(true);
      setError('');
      if (!sending.current) runId.current = snapshot.active_run?.run_id ?? null;
    }
  }, []);

  useEffect(() => {
    const invalidate = () => { requestSequence.current++; };
    const sync = () => { void refresh().catch((cause: unknown) => setError(cause instanceof Error ? cause.message : '会话加载失败')); };
    sync();
    const timer = window.setInterval(sync, 1500);
    window.addEventListener('focus', sync);
    return () => { window.clearInterval(timer); window.removeEventListener('focus', sync); invalidate(); };
  }, [refresh]);

  const send = useCallback(async (input: Omit<ChatMessageInput, 'run_id'>): Promise<void> => {
    if (sending.current || session.active_run) throw new Error('当前回复尚未结束');
    sending.current = true;
    setPending(true);
    try {
      const run = await submitChatMessage({ ...input, run_id: crypto.randomUUID() });
      runId.current = run.run_id;
      let status = run;
      while (status.status === 'running') {
        await new Promise(resolve => window.setTimeout(resolve, 350));
        status = await readChatRun(run.run_id);
      }
      await refresh();
      if (status.status !== 'completed') throw new Error(status.error || '本次回复未完成');
    } finally {
      sending.current = false;
      setPending(false);
      await refresh().catch((cause: unknown) => setError(cause instanceof Error ? cause.message : '会话加载失败'));
    }
  }, [refresh, session.active_run]);

  const stop = useCallback(async (): Promise<void> => {
    if (runId.current) await stopChatRun(runId.current);
    await refresh();
  }, [refresh]);
  return { session, ready, error, busy: pending || session.active_run !== null, send, stop };
}
