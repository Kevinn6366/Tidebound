import { useEffect, useState, type JSX, type FormEvent } from 'react';
import { loadContextBudget, saveContextBudget, type ContextUsage } from '../services/chatClient';

/**
 * 以默认收起的折叠区域提供当前管理员账号的持久化上下文预算编辑。
 * @returns 预算输入、保存反馈与生效范围说明。
 */
export default function ContextBudgetSettings(): JSX.Element {
  const [budget, setBudget] = useState<ContextUsage | null>(null);
  const [value, setValue] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  useEffect(() => {
    let cancelled = false;
    loadContextBudget().then(result => {
      if (cancelled) return;
      setBudget(result);
      setValue(String(result.total));
    }).catch((cause: unknown) => {
      if (!cancelled) setError(cause instanceof Error ? cause.message : '预算加载失败');
    });
    return () => { cancelled = true; };
  }, []);

  /**
   * 校验输入并等待服务端确认保存，不提前宣称生效。
   * @param event - 预算表单提交事件。
   * @returns 保存结束后更新已确认额度与反馈。
   */
  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const limit = Number(value);
    if (!budget || saving) return;
    setNotice('');
    if (!Number.isSafeInteger(limit) || limit < 2048 || limit <= budget.output_reserved + budget.format_margin) {
      setError('请输入大于回复预留与格式余量之和的整数。');
      return;
    }
    setSaving(true);
    setError('');
    try {
      const saved = await saveContextBudget(limit);
      setBudget(saved);
      setValue(String(saved.total));
      setNotice('已保存，下一轮对话生效');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '预算保存失败');
    } finally {
      setSaving(false);
    }
  }

  return <details className="dev-budget">
    <summary>上下文总预算</summary>
    <form onSubmit={event => { void submit(event); }}>
      <label htmlFor="dev-context-limit">上下文总预算</label>
      <input id="dev-context-limit" type="number" min={budget ? Math.max(2048, budget.output_reserved + budget.format_margin + 1) : 2048}
        step="1" value={value} disabled={!budget || saving}
        onChange={event => { setValue(event.target.value); setNotice(''); }} />
      {budget && <p>回复预留 {budget.output_reserved.toLocaleString()} · 余量 {budget.format_margin.toLocaleString()}</p>}
      <p>仅当前账号，重启后保留。输入按字节保守估算，总预算请按模型支持范围设置。</p>
      <button type="submit" disabled={!budget || saving || value === String(budget.total)}>
        {saving ? '保存中…' : '保存预算'}
      </button>
      {error && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
    </form>
  </details>;
}
