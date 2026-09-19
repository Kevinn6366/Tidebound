import { useEffect, useRef, useState } from 'react';
import type { JSX } from 'react';
import { loadModelRequestBody, loadModelRequestRuns } from '../services/consoleClient';
import type { ModelRequestDetail, ModelRequestRun } from '../services/consoleClient';

/**
 * 先选择一次对话，再通过子菜单查看每次实际发送的上下文。
 * @param props - 管理员身份参数。
 * @param props.uid - 当前管理员 UID。
 * @returns 对话列表、模型请求子菜单及分段上下文。
 */
export default function ConsoleRequests({ uid }: { uid: string }): JSX.Element {
  const initialRun = useRef(new URLSearchParams(window.location.hash.split('?')[1]).get('run'));
  const [filter, setFilter] = useState('');
  const [loading, setLoading] = useState(true);
  const [runs, setRuns] = useState<ModelRequestRun[]>([]);
  const [selectedRun, setSelectedRun] = useState<ModelRequestRun | null>(null);
  const [selected, setSelected] = useState('');
  const [offset, setOffset] = useState(0);
  const [detail, setDetail] = useState<{ id: string; data: ModelRequestDetail | null; error: string }>({ id: '', data: null, error: '' });
  const [error, setError] = useState('');
  const [historyCollapsed, setHistoryCollapsed] = useState(false);
  const activeRun = runs.find(run => run.run_id === selectedRun?.run_id && run.owner === selectedRun.owner) ?? selectedRun;
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    /** 串行刷新对话组，保持选择并展示正在增加的调用子菜单。 */
    async function refresh(): Promise<void> {
      try {
        const result = await loadModelRequestRuns(uid, offset, controller.signal);
        if (!controller.signal.aborted) {
          setRuns(result); setError(''); setLoading(false);
          if (initialRun.current) {
            const match = result.find(run => run.run_id === initialRun.current);
            if (match) { setSelectedRun(match); setSelected(match.requests[0]?.request_id ?? ''); }
            initialRun.current = null;
          }
        }
      } catch (failure) {
        if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : '对话列表读取失败');
      } finally {
        if (!controller.signal.aborted) timer = setTimeout(refresh, 2000);
      }
    }
    void refresh();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [uid, offset]);
  useEffect(() => {
    if (!selected) return;
    const controller = new AbortController();
    /** 读取所选请求，切换后不显示迟到的旧正文。 */
    async function readBody(): Promise<void> {
      try {
        const data = await loadModelRequestBody(uid, selected, controller.signal);
        if (!controller.signal.aborted) setDetail({ id: selected, data, error: '' });
      } catch (failure) {
        if (!controller.signal.aborted) setDetail({ id: selected, data: null,
          error: failure instanceof Error ? failure.message : '完整请求读取失败' });
      }
    }
    void readBody();
    return () => controller.abort();
  }, [uid, selected]);

  /**
   * 进入一轮对话，默认选择第一次模型请求。
   * @param run - 所选对话及其完整调用子菜单。
   */
  function openRun(run: ModelRequestRun): void {
    setSelectedRun(run);
    setSelected(run.requests[0]?.request_id ?? '');
  }

  const data = detail.id === selected ? detail.data : null;
  // 最后一条 user 是本轮输入；之前的非 system 消息才是历史。
  const currentUserIndex = data?.messages.map(message => message.role).lastIndexOf('user') ?? -1;
  const historyCount = data?.messages.filter((message, index) => index < currentUserIndex && message.role !== 'system').length ?? 0;
  const filteredRuns = runs.filter(run => `${run.user_content} ${run.run_id} ${run.owner}`.toLowerCase().includes(filter.toLowerCase()));
  return <section className="console-requests console-panel" aria-label="完整模型请求">
    <h2>完整 LLM 对话上下文</h2>
    {!activeRun ? <>
      <p>每次发送的消息是一轮对话。进入后可查看这一轮每次发送给 LLM 的完整上下文。</p>
      <div className="console-request-pages">
        <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))}>较新对话</button>
        <span>第 {offset / 50 + 1} 页 · 每页最多 50 轮</span>
        <button disabled={runs.length < 50} onClick={() => setOffset(offset + 50)}>较早对话</button>
      </div>
      <label className="console-search-label">筛选当前页<input type="search" placeholder="输入对话内容、Run ID 或账号归属" value={filter} onChange={event => setFilter(event.target.value)} /></label>
      <div className="console-run-list">
        {runs.length === 0 && <p className="console-empty">{error ? '暂时无法读取记录。' : loading ? '正在加载对话…' : '暂无记录，新对话会显示在这里。'}</p>}
        {runs.length > 0 && filteredRuns.length === 0 && <p className="console-empty">当前页没有匹配的对话。</p>}
        {filteredRuns.map(run => <button key={`${run.owner}:${run.run_id}`} onClick={() => openRun(run)}>
          <strong>{run.user_content || (run.requests.some(request => request.purpose === 'chat.meet') ? '登录问候' : '未记录输入')}</strong>
          <span>{new Date(run.created_at).toLocaleString()} · {run.requests.length} 次模型请求</span>
          <small>Run {run.run_id.slice(0, 8)} · 归属 {run.owner}</small>
        </button>)}
      </div>
    </> : <>
      <button onClick={() => { setSelectedRun(null); setSelected(''); }}>返回对话列表</button>
      <h3 className="console-run-title">{activeRun.user_content || (activeRun.requests.some(request => request.purpose === 'chat.meet') ? '登录问候' : '未记录输入')}</h3>
      <p>{new Date(activeRun.created_at).toLocaleString()} · {activeRun.requests.length} 次模型请求</p>
      <nav className="console-call-menu" aria-label="本轮模型请求">
        {activeRun.requests.map(request => <button key={request.request_id}
          aria-pressed={selected === request.request_id} onClick={() => setSelected(request.request_id)}>
          {request.purpose === 'tools.websearch.delivery' ? '搜索正式续答' : request.purpose === 'tools.websearch.reaction' ? '搜索第一反应' : request.purpose === 'tools.websearch.context' ? '搜索语境概括' : request.purpose === 'tools.websearch.impression' ? '搜索阅读印象' : request.purpose === 'workflow.followup' ? '跟进摘要' : request.purpose === 'context.compaction' ? '后台压缩' : request.purpose === 'chat.meet' ? '登录问候' : '主回复'} · 第 {request.step} 次请求
        </button>)}
      </nav>
      {detail.id === selected && detail.error && <p role="alert" className="account-error">{detail.error}</p>}
      {!data ? <p>{detail.id === selected && detail.error ? '无法显示该请求正文。' : '正在读取完整上下文…'}</p> : <>
        {data.injection !== '' && <section className="console-injection" aria-label="本次请求注入">
          <h3>本次请求注入</h3>
          {data.injection === null ? <p>旧记录未单独保存注入标记，请查看下方 system 正文；这不代表没有注入。</p>
            : <>
              <p>本次实际附加到 system 的规则，包含持续至本轮结束的规则。</p><pre>{data.injection}</pre>
            </>}
        </section>}
        {historyCount > 0 && <button aria-expanded={!historyCollapsed} onClick={() => setHistoryCollapsed(!historyCollapsed)}>
          {historyCollapsed ? '展开历史对话' : '折叠历史对话'}（{historyCount} 条）
        </button>}
        <div className="console-context-messages" aria-label="完整上下文消息">
          {data.messages.map((message, index) => <details className="console-context-message" key={`${selected}:${index}`}
            open={!(historyCollapsed && index < currentUserIndex && message.role !== 'system')}>
            <summary>{index + 1}. {message.role}{message.toolCallId ? ` · ${message.toolCallId}` : ''}</summary>
            {message.content && <pre>{message.content}</pre>}
            {message.reasoning !== null && <details><summary>reasoning_content</summary><pre>{message.reasoning}</pre></details>}
            {message.toolCalls !== null && <><h4>工具调用</h4><pre>{message.toolCalls}</pre></>}
          </details>)}
        </div>
        <details className="console-context-message"><summary>工具声明 tools</summary><pre>{data.tools}</pre></details>
        <details className="console-context-message"><summary>原始请求 JSON（完整）</summary>
          <pre aria-label="完整模型请求正文">{data.raw}</pre>
        </details>
      </>}
    </>}
    {error && <p role="alert" className="account-error">{error}</p>}
  </section>;
}
