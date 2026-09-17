import { useCallback, useEffect, useRef, useState } from 'react';
import { recordDisplayStart, testMeetWorkflow, prepareMeet, loadChatSession, readChatRun, resetChatContext, streamChatRun, stopChatRun, submitChatMessage, type ChatMessageInput, type SessionView } from '../services/chatClient';

const EMPTY: SessionView = { timezone: 'Asia/Shanghai', meet_run: null, context_usage: null, character: 'atri', character_name: '亚托莉', messages: [], active_run: null, tool_runs: [] };

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
  retryMeet: () => Promise<void>;
  testMeet: () => Promise<void>;
  canRetryMeet: boolean;
  markDisplayed: (messageId: string, revision: number) => Promise<void>;
} {
  const [session, setSession] = useState<SessionView>(EMPTY);
  const [pending, setPending] = useState(false);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState('');
  const [meetError, setMeetError] = useState('');
  const [displayError, setDisplayError] = useState('');
  const displayRequests = useRef(new Set<string>());
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
    let cancelled = false;
    let initialized = false;
    const invalidate = (): void => { cancelled = true; requestSequence.current++; };
    /** 每次挂载代表登录后的应用进入，只触发一次预生成，轮询不触发欢迎。 */
    async function initialize(): Promise<void> {
      const sequence = ++requestSequence.current;
      try {
        const snapshot = await prepareMeet();
        if (!cancelled && sequence === requestSequence.current) {
          setSession(snapshot);
          setReady(true);
          runId.current = snapshot.active_run?.run_id ?? null;
        }
      } catch (cause: unknown) {
        if (!cancelled) setMeetError(cause instanceof Error ? cause.message : '问候准备失败');
      } finally {
        initialized = true;
        if (!cancelled) void refresh().catch((cause: unknown) => setError(cause instanceof Error ? cause.message : '会话加载失败'));
      }
    }
    const sync = (): void => {
      if (initialized) void refresh().catch((cause: unknown) => setError(cause instanceof Error ? cause.message : '会话加载失败'));
    };
    void initialize();
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
                ...(run.kind === 'chat' ? [{ id: `${run.run_id}:user`, role: 'user' as const, content: run.user_content, kind: run.kind, created_at: run.created_at, time_estimated: false, display_revision: 0, display_pending: false }] : []),
                { id: `${run.run_id}:assistant`, role: 'assistant' as const, content: run.reply!, kind: run.kind, created_at: run.display_started_at || (run.display_pending ? null : run.completed_at || run.created_at), time_estimated: !run.display_started_at, display_revision: run.display_revision, display_pending: run.display_pending },
              ] : previous.messages;
              return { ...previous, messages, active_run: null,
                meet_run: run.kind === 'meet' ? run : run.status === 'completed' ? null : previous.meet_run,
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
      setMeetError('');
    } finally {
      resettingRef.current = false;
      setResetting(false);
      await refresh();
    }
  }, [refresh]);
  /**
   * 请求欢迎重试或管理员主动测试，并同步当前执行。
   * @param mode - 重试保留登录去重，测试由服务端验证管理员权限并跳过冷却。
   * @returns 完成执行状态同步，模型继续在后台运行。
   * @throws 管理员测试请求失败时向工具箱返回错误。
   */
  const runMeet = useCallback(async (mode: 'retry' | 'test'): Promise<void> => {
    if (resettingRef.current || sending.current || session.active_run) return;
    sending.current = true;
    setPending(true);
    setMeetError('');
    const generation = resetGeneration.current;
    requestSequence.current++;
    try {
      const snapshot = await (mode === 'test' ? testMeetWorkflow() : prepareMeet(true));
      if (generation !== resetGeneration.current) return;
      requestSequence.current++;
      setSession(snapshot);
      runId.current = snapshot.active_run?.run_id ?? null;
    } catch (cause: unknown) {
      if (mode === 'test') throw cause;
      setMeetError(cause instanceof Error ? cause.message : '问候准备失败');
    } finally {
      sending.current = false;
      setPending(false);
    }
  }, [session.active_run]);
  /**
   * 只在当前角色正文首次出现时确认展示，刷新与多标签页由服务端共同去重。
   * @param messageId - 页面显示消息标识，包含对应 Run ID。
   * @param revision - 服务端正文版本，防止工具过渡文字迟到覆盖。
   * @returns 完成时间同步；保存错误显示在聊天区。
   */
  const markDisplayed = useCallback(async (messageId: string, revision: number): Promise<void> => {
    const key = `${messageId}:${revision}`;
    if (displayRequests.current.has(key) || resettingRef.current) return;
    displayRequests.current.add(key);
    const generation = resetGeneration.current;
    try {
      const run = await recordDisplayStart(messageId.split(':')[0], revision);
      if (!run || generation !== resetGeneration.current) return;
      setDisplayError('');
      // 只合并时间字段，迟到确认不能把旧运行状态或正文恢复到当前页面。
      setSession(previous => ({ ...previous,
        messages: previous.messages.map(message => message.id === messageId && message.display_revision === revision
          ? { ...message, created_at: run.display_started_at, display_pending: false, time_estimated: false } : message),
      }));
    } catch (cause: unknown) {
      displayRequests.current.delete(key);
      if (generation === resetGeneration.current) setDisplayError(cause instanceof Error ? cause.message : '展示时间保存失败');
    }
  }, []);
  const greetingError = session.meet_run && !['running', 'completed'].includes(session.meet_run.status)
    ? session.meet_run.error || '问候已停止，可重试或直接开始聊天。' : '';
  return { session, ready, error: error || displayError || meetError || greetingError,
    busy: !ready || resetting || pending || session.active_run !== null, send, stop, reset, resetting, markDisplayed, retryMeet: () => runMeet('retry'), testMeet: () => runMeet('test'), canRetryMeet: Boolean(meetError || greetingError) };

}
