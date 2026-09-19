import { frontendFetch } from './frontendFetch';

export type ChannelId = 'siliconflow' | 'codex789';
export interface ModelChannel {
  id: ChannelId;
  name: string;
  model: string;
  base_url: string;
  ready: boolean;
}
export interface ModelChannels {
  selected: ChannelId;
  channels: ModelChannel[];
}

function isChannel(value: unknown): value is ChannelId {
  return value === 'siliconflow' || value === 'codex789';
}

/**
 * 校验后端渠道视图，不接收或展示凭据。
 * @param value - 未知的 JSON 响应。
 * @returns 类型完整的渠道状态。
 * @throws 服务端响应结构非法。
 */
function parseChannels(value: unknown): ModelChannels {
  if (typeof value !== 'object' || value === null || !('selected' in value) || !isChannel(value.selected)
    || !('channels' in value) || !Array.isArray(value.channels)) throw new Error('渠道响应格式非法');
  const channels = value.channels.map((item: unknown): ModelChannel => {
    if (typeof item !== 'object' || item === null || !('id' in item) || !isChannel(item.id)
      || !('name' in item) || typeof item.name !== 'string'
      || !('model' in item) || typeof item.model !== 'string'
      || !('base_url' in item) || typeof item.base_url !== 'string'
      || !('ready' in item) || typeof item.ready !== 'boolean') throw new Error('渠道响应格式非法');
    return { id: item.id, name: item.name, model: item.model, base_url: item.base_url, ready: item.ready };
  });
  return { selected: value.selected, channels };
}

/**
 * 读取服务级主聊天渠道。
 * @param uid - 当前管理员 UID。
 * @param signal - 页面卸载时取消读取。
 * @returns 当前选择及可切换渠道。
 * @throws 请求失败或响应格式非法。
 */
export async function loadModelChannels(uid: string, signal: AbortSignal): Promise<ModelChannels> {
  const response = await frontendFetch(`/api/users/${encodeURIComponent(uid)}/console/model-channels`, { signal });
  return parseChannels(await response.json());
}

/**
 * 将管理员选择应用于后续主聊天。
 * @param uid - 当前管理员 UID。
 * @param channel - 服务端已配置的渠道标识。
 * @returns 已持久化的新选择。
 * @throws 权限不足、配置缺失或请求失败。
 */
export async function selectModelChannel(uid: string, channel: ChannelId): Promise<ModelChannels> {
  const response = await frontendFetch(`/api/users/${encodeURIComponent(uid)}/console/model-channels`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ channel }),
  });
  return parseChannels(await response.json());
}
