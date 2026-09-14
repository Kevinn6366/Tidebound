import { useCallback, useEffect, useRef, useState } from 'react';
import { loadChatSession, readChatRun, resetChatContext, streamChatRun, stopChatRun, submitChatMessage, type ChatMessageInput, type SessionView } from '../services/chatClient';

const EMPTY: SessionView = { context_usage: null, character: 'atri', character_name: '亚托莉', messages: [], active_run: null, tool_runs: [] };

/**
 * 维护服务端会话的展示副本，重连只查询，不重放用户输入。
 * @returns 固定角色的历史、忙碌状态、发送与显式停止入口。
 */
export function useAgentChat(): {
  session: SessionView; ready: boolean; error: string; busy: boolean;
  send: (input: Omit<ChatMessageInput, 'run_id'>) => Promise<void>;
  stop: () => Promise<void>;
  reset: () => Promise<void>;
  resetting: boolean;
} {
  const [session, setSession] = useState<SessionView>(EMPTY);
  const [pending, setPending] = useState(false);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState('');
  const [resetting, setResetting] = useState(false);
  const resettingRef = useRef(false);
  const resetGeneration = useRef(0);
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

  const activeRunId = session.active_run?.run_id;
  useEffect(() => {
    if (!activeRunId) return;
    const controller = new AbortController();
    /** 订阅当前执行，断线只恢复订阅；状态快照不会重复追加文字。 */
    async function follow(): Promise<void> {
      while (!controller.signal.aborted) {
        try {
          await streamChatRun(activeRunId!, controller.signal, run => {
            if (controller.signal.aborted || resettingRef.current) return;
            requestSequence.current++;
            setSession(previous => {
              if (previous.active_run?.run_id !== run.run_id) return previous;
              if (run.status === 'running') return { ...previous, active_run: run, context_usage: run.context_usage ?? previous.context_usage };
              const messages = run.status === 'completed' ? [
                ...previous.messages.filter(message => !message.id.startsWith(`${run.run_id}:`)),
                { id: `${run.run_id}:user`, role: 'user' as const, content: run.user_content },
                { id: `${run.run_id}:assistant`, role: 'assistant' as const, content: run.reply! },
              ] : previous.messages;
              return { ...previous, messages, active_run: null,
                context_usage: run.status === 'completed' ? run.context_usage ?? previous.context_usage : previous.context_usage };
            });
          });
          return;
        } catch (cause) {
          if (controller.signal.aborted) return;
          setError(cause instanceof Error ? cause.message : '流式连接已中断');
          await new Promise(resolve => window.setTimeout(resolve, 500));
        }
      }
    }
    void follow();
    return () => controller.abort();
  }, [activeRunId]);

  const send = useCallback(async (input: Omit<ChatMessageInput, 'run_id'>): Promise<void> => {
    if (resettingRef.current || sending.current || session.active_run) throw new Error('当前回复尚未结束');
    const generation = resetGeneration.current;
    sending.current = true;
    setPending(true);
    try {
      const run = await submitChatMessage({ ...input, run_id: crypto.randomUUID() });
      if (generation !== resetGeneration.current) return;
      runId.current = run.run_id;
      if (run.status === 'running') setSession(previous => ({ ...previous, active_run: run }));
      let status = run;
      while (status.status === 'running') {
        await new Promise(resolve => window.setTimeout(resolve, 350));
        status = await readChatRun(run.run_id);
        if (generation !== resetGeneration.current) return;
      }
      if (generation !== resetGeneration.current) return;
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
  /** 清空服务端有效上下文并使旧订阅和查询失效。 */
  const reset = useCallback(async (): Promise<void> => {
    if (resettingRef.current) return;
    resettingRef.current = true;
    setResetting(true);
    resetGeneration.current++;
    requestSequence.current++;
    try {
      const snapshot = await resetChatContext();
      requestSequence.current++;
      setSession(snapshot);
      runId.current = null;
      setError('');
    } finally {
      resettingRef.current = false;
      setResetting(false);
      await refresh();
    }
  }, [refresh]);
  return { session, ready, error, busy: resetting || pending || session.active_run !== null, send, stop, reset, resetting };
}
