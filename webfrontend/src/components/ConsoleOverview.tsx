import { useEffect, useState } from 'react';
import type { JSX } from 'react';
import { Activity, ArrowRight, Cpu, Layers, MessagesSquare, RefreshCw } from 'lucide-react';
import { loadModelRequestRuns } from '../services/consoleClient';
import type { ModelRequestRun } from '../services/consoleClient';
import { loadModelChannels } from '../services/modelChannelsClient';
import type { ModelChannels } from '../services/modelChannelsClient';

/**
 * 读取有界的最近记录与真实配置，汇总管理员工作概览。
 * @param props - 身份参数。
 * @param props.uid - 当前管理员编号。
 * @returns 概览指标、最近对话和快捷入口。
 */
export default function ConsoleOverview({ uid }: { uid: string }): JSX.Element {
  const [snapshot, setSnapshot] = useState<{ runs: ModelRequestRun[]; channels: ModelChannels; time: string } | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    const deadline = setTimeout(() => controller.abort(), 8000);
    let active = true;
    Promise.all([loadModelRequestRuns(uid, 0, controller.signal), loadModelChannels(uid, controller.signal)])
      .then(([runs, channels]) => { if (active) { setSnapshot({ runs, channels, time: new Date().toLocaleTimeString() }); setError(''); } })
      .catch((cause: unknown) => { if (active) setError(controller.signal.aborted ? '读取超时，请刷新重试。' : cause instanceof Error ? cause.message : '读取概览失败'); })
      .finally(() => { clearTimeout(deadline); if (active) setLoading(false); });
    return () => { active = false; controller.abort(); clearTimeout(deadline); };
  }, [uid, revision]);
  const selected = snapshot?.channels.channels.find(channel => channel.id === snapshot.channels.selected);
  return <>
    <div className="console-overview-toolbar"><p>{snapshot ? `快照更新于 ${snapshot.time} · 最近 50 轮以内的审计记录` : '正在读取服务记录…'}</p>
      <button disabled={loading} onClick={() => { setLoading(true); setRevision(value => value + 1); }}><RefreshCw size={14} />{loading ? '读取中…' : '刷新概览'}</button></div>
    {error && <p role="alert" className="account-error">{error}</p>}
    <div className="console-metrics">
      <article className="console-metric console-metric-model"><div><span>主聊天模型</span><Cpu size={19} /></div><strong>{selected?.model || (snapshot ? '未配置' : '—')}</strong><small>{selected?.name || '等待读取配置'} · 从下一轮生效</small></article>
      <article className="console-metric"><div><span>最近对话</span><MessagesSquare size={19} /></div><strong>{snapshot ? snapshot.runs.length : '—'}<em>轮</em></strong><small>当前快照 · 非历史总量</small></article>
      <article className="console-metric"><div><span>模型调用记录</span><Layers size={19} /></div><strong>{snapshot ? snapshot.runs.reduce((sum, run) => sum + run.requests.length, 0) : '—'}<em>次</em></strong><small>最近对话中的请求尝试</small></article>
    </div>
    <div className="console-overview-grid">
      <section className="console-panel"><div className="console-panel-heading"><div><h2>最近对话</h2><p>从对话进入，查看完整模型调用链</p></div><a href="#context">全部记录 <ArrowRight size={14} /></a></div>
        <div className="console-recent-list">
          {snapshot?.runs.slice(0, 5).map(run => <a href={`#context?run=${encodeURIComponent(run.run_id)}`} key={`${run.owner}:${run.run_id}`} className="console-recent-row">
            <span className="console-row-icon"><MessagesSquare size={17} /></span><span className="console-recent-text"><strong>{run.user_content || (run.requests.some(request => request.purpose === 'chat.meet') ? '登录问候' : '未记录输入')}</strong><small>{new Date(run.created_at).toLocaleString()} · {run.requests.length} 次调用</small></span><ArrowRight size={16} /></a>)}
          {snapshot?.runs.length === 0 && <div className="console-empty">暂无对话记录。开始对话后，可在这里检查模型请求。</div>}
          {!snapshot && <div className="console-empty">{error ? '暂时无法显示记录，请重试。' : '正在加载最近对话…'}</div>}
        </div>
      </section>
      <section className="console-panel console-shortcuts"><div className="console-panel-heading"><div><h2>工作入口</h2><p>调试与配置，各归其位</p></div></div>
        <a href="#log"><Activity size={20} /><span><strong>追踪运行日志</strong><small>工作流、工具与执行状态</small></span><ArrowRight size={16} /></a>
        <a href="#models"><Cpu size={20} /><span><strong>切换模型渠道</strong><small>查看配置与当前来源</small></span><ArrowRight size={16} /></a>
        <div className="console-scope-note"><span className="console-status-dot" />审计范围<p>展示本服务内的管理员审计记录。请求快照表示发送尝试，不代表调用已成功。</p></div>
      </section>
    </div>
  </>;
}
