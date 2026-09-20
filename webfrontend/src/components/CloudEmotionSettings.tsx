import { useEffect, useState, type JSX } from 'react';
import {
  loadEmotionEnhancement,
  saveEmotionEnhancement,
  type EmotionEnhancementSettings,
} from '../services/chatClient';

/**
 * 在聊天底部菜单展示当前账号的云端情感增强开关，只呈现服务端确认的状态。
 * @param props - 菜单操作的反馈入口。
 * @param props.onFeedback - 通过聊天页提示展示保存结果或可重试错误。
 * @returns 显示开关状态、支持切换或重新加载的菜单按钮。
 */
export default function CloudEmotionSettings({ onFeedback }: {
  onFeedback: (message: string, type: 'success' | 'error') => void;
}): JSX.Element {
  const [settings, setSettings] = useState<EmotionEnhancementSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    loadEmotionEnhancement().then(result => {
      if (!cancelled) setSettings(result);
    }).catch((cause: unknown) => {
      if (!cancelled) {
        const message = cause instanceof Error ? cause.message : '情感增强配置加载失败';
        setError(message);
        onFeedback(message, 'error');
      }
    });
    return () => { cancelled = true; };
  }, [reloadKey, onFeedback]);

  /**
   * 重试读取失败的设置，或切换当前账号的润色开关；保存失败时保留已确认状态。
   * @returns 保存成功后显示下一轮生效提示，失败时通过聊天页提示错误。
   */
  async function toggle(): Promise<void> {
    if (saving) return;
    if (!settings) {
      setError('');
      setReloadKey(value => value + 1);
      return;
    }
    if (!settings.configured && !settings.enabled) return;
    setSaving(true);
    setError('');
    try {
      const saved = await saveEmotionEnhancement(!settings.enabled);
      setSettings(saved);
      onFeedback(`情感增强已${saved.enabled ? '开启' : '关闭'}，下一轮对话生效`, 'success');
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : '情感增强设置保存失败';
      setError(message);
      onFeedback(message, 'error');
    } finally {
      setSaving(false);
    }
  }

  const unavailable = settings !== null && !settings.configured && !settings.enabled;
  const title = error ? `${error}，点击重试` : unavailable
    ? '云端模型尚未配置，暂时无法开启。'
    : `云端情感增强：${settings?.enabled ? '已开启' : '已关闭'}，点击切换，下一轮对话生效`;
  const state = saving ? '保存中…' : settings ? settings.enabled ? '开' : '关' : error ? '重试' : '加载中…';

  return <button type="button" aria-label="云端情感增强" aria-pressed={settings?.enabled ?? false}
    title={title} disabled={saving || (!settings && !error) || unavailable}
    className="cursor-pointer hover:text-white transition-colors shrink-0 whitespace-nowrap rounded-sm focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-indigo-300 disabled:opacity-50 disabled:cursor-default"
    onClick={() => { void toggle(); }}>
    情感增强 · {state}
  </button>;
}
