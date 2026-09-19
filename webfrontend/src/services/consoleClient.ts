import { frontendFetch } from './frontendFetch';

export interface ConsoleLog {
  filename: string;
  content: string;
  exists: boolean;
  truncated: boolean;
  eventsContent: string;
}

/**
 * 读取管理员可见的固定调试日志尾部。
 * @param uid - 已登录管理员的 UID。
 * @param signal - 页面卸载时取消请求的信号。
 * @returns 已校验的日志快照。
 * @throws 网络、权限或响应结构错误。
 */
export async function loadConsoleLog(uid: string, signal: AbortSignal): Promise<ConsoleLog> {
  const response = await frontendFetch(`/api/users/${encodeURIComponent(uid)}/console/log`, { signal });
  const data: unknown = await response.json();
  if (typeof data !== 'object' || data === null
    || !('filename' in data) || typeof data.filename !== 'string'
    || !('content' in data) || typeof data.content !== 'string'
    || !('exists' in data) || typeof data.exists !== 'boolean'
    || !('truncated' in data) || typeof data.truncated !== 'boolean') throw new Error('日志响应格式非法');
  return { filename: data.filename, content: data.content, exists: data.exists, truncated: data.truncated,
    eventsContent: 'events_content' in data && typeof data.events_content === 'string' ? data.events_content : '' };
}

export interface ModelRequestSummary {
  request_id: string;
  run_id: string;
  owner: string;
  step: number;
  created_at: string;
  model: string;
  purpose: string;
}

/**
 * 校验模型请求摘要，拒绝未知的响应结构。
 * @param data - 服务端返回的未知数据。
 * @returns 可用于展示的请求摘要。
 * @throws 摘要字段非法。
 */
function parseRequestSummary(data: unknown): ModelRequestSummary {
  if (typeof data !== 'object' || data === null
    || !('request_id' in data) || typeof data.request_id !== 'string'
    || !('run_id' in data) || typeof data.run_id !== 'string'
    || !('owner' in data) || typeof data.owner !== 'string'
    || !('step' in data) || typeof data.step !== 'number'
    || !('created_at' in data) || typeof data.created_at !== 'string'
    || !('model' in data) || typeof data.model !== 'string'
    || ('purpose' in data && typeof data.purpose !== 'string')) throw new Error('模型请求摘要格式非法');
  return { request_id: data.request_id, run_id: data.run_id, owner: data.owner,
    step: data.step, created_at: data.created_at, model: data.model,
    purpose: 'purpose' in data && typeof data.purpose === 'string' ? data.purpose : 'chat' };
}

export interface ModelRequestRun {
  run_id: string;
  owner: string;
  created_at: string;
  user_content: string;
  requests: ModelRequestSummary[];
}

export interface ContextMessage {
  role: string;
  content: string;
  reasoning: string | null;
  toolCalls: string | null;
  toolCallId: string | null;
}

export interface ModelRequestDetail {
  raw: string;
  messages: ContextMessage[];
  tools: string;
  injection: string | null;
}

/**
 * 按完整对话读取模型请求子菜单，同一对话不会跨页拆开。
 * @param uid - 当前管理员 UID。
 * @param offset - 从最新对话起跳过的组数。
 * @param signal - 取消请求的信号。
 * @returns 最多 50 个对话组。
 * @throws 网络、权限或响应格式错误。
 */
export async function loadModelRequestRuns(uid: string, offset: number, signal: AbortSignal): Promise<ModelRequestRun[]> {
  const response = await frontendFetch(`/api/users/${encodeURIComponent(uid)}/console/request-runs?offset=${offset}`, { signal });
  const data: unknown = await response.json();
  if (!Array.isArray(data)) throw new Error('对话分组格式非法');
  return data.map((item: unknown) => {
    if (typeof item !== 'object' || item === null
      || !('run_id' in item) || typeof item.run_id !== 'string'
      || !('owner' in item) || typeof item.owner !== 'string'
      || !('created_at' in item) || typeof item.created_at !== 'string'
      || !('user_content' in item) || typeof item.user_content !== 'string'
      || !('requests' in item) || !Array.isArray(item.requests)) throw new Error('对话分组格式非法');
    return { run_id: item.run_id, owner: item.owner, created_at: item.created_at,
      user_content: item.user_content, requests: item.requests.map(parseRequestSummary) };
  });
}

/**
 * 校验一条模型消息并保留正文与工具字段。
 * @param data - 请求中的未知消息对象。
 * @returns 适合分段显示的消息。
 * @throws 消息正文或角色结构非法。
 */
function parseContextMessage(data: unknown): ContextMessage {
  if (typeof data !== 'object' || data === null || !('role' in data) || typeof data.role !== 'string'
    || !('content' in data) || (data.content !== null && typeof data.content !== 'string')) throw new Error('上下文消息格式非法');
  return { role: data.role, content: data.content ?? '',
    reasoning: 'reasoning_content' in data && typeof data.reasoning_content === 'string' ? data.reasoning_content : null,
    toolCalls: 'tool_calls' in data ? JSON.stringify(data.tool_calls, null, 2) : null,
    toolCallId: 'tool_call_id' in data && typeof data.tool_call_id === 'string' ? data.tool_call_id : null };
}

/**
 * 读取单次模型请求的完整正文与当次注入标记。
 * @param uid - 当前管理员 UID。
 * @param requestId - 选中的请求 UUID。
 * @param signal - 取消请求的信号。
 * @returns 未截断的原始 JSON、消息及注入信息；旧快照注入标记为 null。
 * @throws 网络、权限或响应格式错误。
 */
export async function loadModelRequestBody(uid: string, requestId: string, signal: AbortSignal): Promise<ModelRequestDetail> {
  const response = await frontendFetch(`/api/users/${encodeURIComponent(uid)}/console/requests/${encodeURIComponent(requestId)}`, { signal });
  const data: unknown = await response.json();
  parseRequestSummary(data);
  if (typeof data !== 'object' || data === null || !('body' in data)
    || typeof data.body !== 'object' || data.body === null || Array.isArray(data.body)
    || !('messages' in data.body) || !Array.isArray(data.body.messages)) throw new Error('模型请求正文格式非法');
  return { raw: JSON.stringify(data.body, null, 2), messages: data.body.messages.map(parseContextMessage),
    tools: JSON.stringify('tools' in data.body ? data.body.tools : [], null, 2),
    injection: 'injection' in data && typeof data.injection === 'string' ? data.injection : null };
}
