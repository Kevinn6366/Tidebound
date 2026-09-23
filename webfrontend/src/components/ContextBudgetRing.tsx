import type { JSX } from 'react';
import type { ContextUsage } from '../services/chatClient';

/**
 * 显示最近模型请求的预算占用圆环，点击查看明细，鼠标离开圆环及弹窗区域时收起。
 * @param props - 后端统计的预算数据。
 * @param props.usage - 最近实际请求用量或尚未请求的配置。
 * @returns 支持鼠标、触屏和键盘展开的圆环及详情。
 */
export default function ContextBudgetRing({ usage }: { usage: ContextUsage | null }): JSX.Element {
  const known = usage !== null && usage.input_used !== null;
  const used = known ? usage.input_used! + usage.output_reserved + usage.format_margin : 0;
  const percent = known ? Math.min(100, Math.round(used / usage.total * 100)) : null;
  const ratio = known ? Math.min(1, used / usage.total) : 0;
  const color = ratio >= 0.95 ? '#fb7185' : ratio >= 0.8 ? '#fbbf24' : '#a5b4fc';
  const label = percent === null ? '上下文预算：尚无请求用量' : `上下文预算已占用 ${percent}%`;
  return <details className="context-budget" onMouseLeave={event => { event.currentTarget.open = false; }}>
    <summary aria-label={label} title={`${label}，点击查看明细`}>
      <svg viewBox="0 0 40 40" aria-hidden="true">
        <circle cx="20" cy="20" r="16" fill="none" stroke="rgba(255,255,255,.16)" strokeWidth="3" />
        <circle cx="20" cy="20" r="16" fill="none" stroke={color} strokeWidth="3" strokeLinecap="round"
          pathLength="100" strokeDasharray={`${ratio * 100} 100`} transform="rotate(-90 20 20)" />
      </svg>
      <span>{percent === null ? '—' : `${percent}%`}</span>
    </summary>
    <div className="context-budget-popover" role="region" aria-label="上下文预算明细">
      <strong>上下文预算</strong>
      {usage ? <dl>
        <div><dt>总预算</dt><dd>{usage.total.toLocaleString()}</dd></div>
        <div><dt>输入估算</dt><dd>{usage.input_used?.toLocaleString() ?? '尚无请求'}</dd></div>
        <div><dt>回复预留</dt><dd>{usage.output_reserved.toLocaleString()}</dd></div>
        <div><dt>格式余量</dt><dd>{usage.format_margin.toLocaleString()}</dd></div>
        {known && <div><dt>剩余预算</dt><dd>{Math.max(0, usage.total - used).toLocaleString()}</dd></div>}
      </dl> : <p>正在读取预算…</p>}
      <p>圆环包含输入估算与预留。输入按 UTF-8 字节保守估算，并非精确 token 用量。</p>
      <p>显示最近请求用量；后台整理完成后更新为当前上下文估算。不包含尚未发送的草稿。</p>
    </div>
  </details>;
}
