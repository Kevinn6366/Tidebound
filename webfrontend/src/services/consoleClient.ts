import { frontendFetch } from './frontendFetch';

export interface ConsoleLog {
  filename: string;
  content: string;
  exists: boolean;
  truncated: boolean;
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
  return { filename: data.filename, content: data.content, exists: data.exists, truncated: data.truncated };
}
