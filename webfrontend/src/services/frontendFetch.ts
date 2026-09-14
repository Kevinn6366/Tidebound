import { getSessionUser, requireSession } from './authClient';

/**
 * 为恢复的上游 UI 集中处理 HTTP 失败，防止设置操作把 501 当作成功。
 * @param input - 原设置组件提供的请求地址或 Request。
 * @param init - 请求方法、请求体与取消信号。
 * @returns 实际服务响应；404 留给媒体列表处理不存在的资源。
 * @throws 未接入业务、网络失败或非本站服务请求时抛出错误。
 */
export async function frontendFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const raw = input instanceof Request ? input.url : String(input);
  const url = new URL(raw, window.location.origin);
  // 本地文件预览仍可读取 Blob / Data URL，HTTP 业务统一走同源通信层。
  if (!['blob:', 'data:'].includes(url.protocol) && url.origin !== window.location.origin) {
    throw new Error('该外部服务尚未接入新后端');
  }
  const headers = new Headers(input instanceof Request ? input.headers : undefined);
  new Headers(init?.headers).forEach((value, key) => headers.set(key, value));
  const user = getSessionUser();
  if (user && url.origin === window.location.origin) headers.set('X-Tidebound-Uid', user.uid);
  const response = await fetch(input, { ...init, headers });
  requireSession(response);
  if (!response.ok && response.status !== 404) {
    throw new Error(response.status === 501 ? '该后端功能尚未接入，原界面与配置已保留' : `请求失败（${response.status}）`);
  }
  return response;
}
