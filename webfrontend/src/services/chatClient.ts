import { getSessionUser } from './authClient';

export interface ChatMessageInput {
  run_id: string;
  content: string;
  attachments: { type: string; name: string; data: string }[];
}
export interface RunView {
  run_id: string;
  status: 'running' | 'completed' | 'stopped' | 'failed' | 'interrupted';
  tools: { call_id: string; name: string; arguments: string; result: string | null }[];
  reply: string | null;
  error: string | null;
}
export interface SessionView {
  character: 'atri';
  character_name: '亚托莉';
  messages: { id: string; role: 'user' | 'assistant'; content: string }[];
  active_run: RunView | null;
  tool_runs: RunView[];
}

/**
 * 读取同源通信结果，保留后端安全错误说明。
 * @param path - 固定的对话接口路径。
 * @param init - 请求方法和正文。
 * @returns 尚需结构校验的响应数据。
 * @throws 网络、HTTP 或 JSON 错误。
 */
async function request(path: string, init?: RequestInit): Promise<unknown> {
  const headers = new Headers(init?.headers);
  const user = getSessionUser();
  if (user) headers.set('X-Tidebound-Uid', user.uid);
  const response = await fetch(path, { ...init, headers, credentials: 'same-origin' });
  const data: unknown = await response.json();
  if (!response.ok) {
    if (typeof data === 'object' && data !== null && 'detail' in data) {
      const detail = data.detail;
      if (typeof detail === 'object' && detail !== null && 'message' in detail && typeof detail.message === 'string') {
        throw new Error(detail.message);
      }
    }
    throw new Error(`请求失败（${response.status}）`);
  }
  return data;
}

/**
 * 检查执行视图，拒绝把非法响应当作成功回复。
 * @param data - 服务端返回的未知数据。
 * @returns 经过结构校验的执行视图。
 * @throws 执行状态或正文类型非法。
 */
function parseRun(data: unknown): RunView {
  if (typeof data !== 'object' || data === null || !('run_id' in data) || typeof data.run_id !== 'string'
    || !('status' in data) || !['running', 'completed', 'stopped', 'failed', 'interrupted'].includes(String(data.status))
    || !('reply' in data) || (data.reply !== null && typeof data.reply !== 'string')
    || !('error' in data) || (data.error !== null && typeof data.error !== 'string')) {
    throw new Error('执行响应格式非法');
  }
  if (!('tools' in data) || !Array.isArray(data.tools) || data.tools.some((tool: unknown) =>
    typeof tool !== 'object' || tool === null
    || !('call_id' in tool) || typeof tool.call_id !== 'string'
    || !('name' in tool) || typeof tool.name !== 'string'
    || !('arguments' in tool) || typeof tool.arguments !== 'string'
    || !('result' in tool) || (tool.result !== null && typeof tool.result !== 'string'))) {
    throw new Error('工具记录格式非法');
  }
  if (data.status === 'completed' && (typeof data.reply !== 'string' || !data.reply.trim())) {
    throw new Error('模型没有返回完整回复');
  }
  return data as RunView;
}

/**
 * 读取固定 atri 的服务端已提交历史。
 * @returns 经结构校验的会话快照。
 * @throws 网络、HTTP 或结构错误。
 */
export async function loadChatSession(): Promise<SessionView> {
  const data = await request('/api/chat/session');
  if (typeof data !== 'object' || data === null || !('character' in data) || data.character !== 'atri'
    || !('character_name' in data) || data.character_name !== '亚托莉'
    || !('tool_runs' in data) || !Array.isArray(data.tool_runs)
    || !('messages' in data) || !Array.isArray(data.messages) || !('active_run' in data)) {
    throw new Error('会话响应格式非法');
  }
  const messages = data.messages.map((item: unknown): SessionView['messages'][number] => {
    if (typeof item !== 'object' || item === null || !('id' in item) || typeof item.id !== 'string'
      || !('role' in item) || (item.role !== 'user' && item.role !== 'assistant')
      || !('content' in item) || typeof item.content !== 'string') throw new Error('历史消息格式非法');
    return { id: item.id, role: item.role, content: item.content };
  });
  return { character: 'atri', character_name: '亚托莉', messages, tool_runs: data.tool_runs.map(parseRun),
    active_run: data.active_run === null ? null : parseRun(data.active_run) };
}

/**
 * 提交正文，不向后端传模型历史、提示词或凭据。
 * @param input - 用户输入与幂等执行 ID。
 * @returns 可查询的执行状态。
 * @throws 后端拒绝或通信失败。
 */
export async function submitChatMessage(input: ChatMessageInput): Promise<RunView> {
  return parseRun(await request('/api/chat/messages', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input),
  }));
}

/**
 * 查询一轮执行。
 * @param id - 后端接受的执行 UUID。
 * @returns 当前执行状态。
 */
export async function readChatRun(id: string): Promise<RunView> {
  return parseRun(await request(`/api/chat/runs/${encodeURIComponent(id)}`));
}

/**
 * 请求停止指定执行；断开页面不调用此接口。
 * @param id - 用户明确要停止的执行 UUID。
 * @returns 后端收到请求时的执行状态。
 */
export async function stopChatRun(id: string): Promise<RunView> {
  return parseRun(await request(`/api/chat/runs/${encodeURIComponent(id)}/stop`, { method: 'POST' }));
}
