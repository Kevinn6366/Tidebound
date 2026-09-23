export interface AuthUser {
  uid: string;
  username: string;
  role: 'user' | 'admin';
}
const USER_KEY = 'tidebound_user';
let redirectingToLogin = false;

/**
 * 私有请求遇到 HTTP 401 时清理身份缓存并回到登录页。
 * @param response - 普通业务接口或流式连接的响应，不用于登录凭据校验。
 * @returns 非 401 响应保持原流程。
 * @throws 会话失效时抛出 HTTP 401 错误，中止后续响应解析。
 */
export function requireSession(response: Response): void {
  if (response.status !== 401) return;
  sessionStorage.removeItem(USER_KEY);
  if (!redirectingToLogin) {
    redirectingToLogin = true;
    window.location.replace('/app/');
  }
  throw new Error('HTTP 401 Unauthorized');
}

/**
 * 读取当前标签页已验证的身份缓存，仅用于界面展示。
 * @returns 当前用户；缺失或非法缓存时返回 null。
 */
export function getSessionUser(): AuthUser | null {
  const raw = sessionStorage.getItem(USER_KEY);
  if (!raw) return null;
  try { return parseUser(JSON.parse(raw)); } catch { return null; }
}

/**
 * 校验后端账号响应，拒绝缺失或非法身份字段。
 * @param data - 未知 JSON 数据。
 * @returns 可用于展示的账号身份。
 * @throws 身份格式不合法。
 */
function parseUser(data: unknown): AuthUser {
  if (typeof data !== 'object' || data === null
    || !('uid' in data) || typeof data.uid !== 'string' || !/^uid-\d{8}$/.test(data.uid)
    || !('username' in data) || typeof data.username !== 'string'
    || !('role' in data) || !['user', 'admin'].includes(String(data.role))) throw new Error('账号响应格式非法');
  return { uid: data.uid, username: data.username, role: data.role as AuthUser['role'] };
}

/**
 * 请求账号 API 并转换服务端公开错误。
 * @param path - 账号 API 子路径。
 * @param body - POST 正文；省略时使用 GET。
 * @returns 尚待校验的响应数据。
 * @throws HTTP 或网络错误。
 */
async function authRequest(path: string, body?: object, setupToken?: string): Promise<unknown> {
  const response = await fetch(`/api/auth/${path}`, {
    credentials: 'same-origin', method: body ? 'POST' : 'GET',
    headers: body ? { 'Content-Type': 'application/json', ...(setupToken ? { 'X-Tidebound-Setup-Token': setupToken } : {}) } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const data: unknown = await response.json();
  if (!response.ok) {
    if (typeof data === 'object' && data !== null && 'detail' in data) {
      if (typeof data.detail === 'string') throw new Error(data.detail);
      if (typeof data.detail === 'object' && data.detail !== null && 'message' in data.detail
        && typeof data.detail.message === 'string') throw new Error(data.detail.message);
    }
    throw new Error(`账号请求失败（${response.status}）`);
  }
  return data;
}

/**
 * 检查首次初始化状态与当前 Cookie 的真实登录身份。
 * @returns 初始化状态及可选账号。
 * @throws 状态格式或网络错误。
 */
export async function loadIdentity(): Promise<{ setup: boolean; passwordlessDebug: boolean; user: AuthUser | null }> {
  sessionStorage.removeItem(USER_KEY);
  const status = await authRequest('status');
  if (typeof status !== 'object' || status === null || !('setup_required' in status)
    || typeof status.setup_required !== 'boolean') throw new Error('初始化状态格式非法');
  const response = await fetch('/api/auth/me', { credentials: 'same-origin' });
  if (response.status === 401) {
    if (window.location.pathname.startsWith('/app/uid-')) requireSession(response);
    if (window.location.hash) window.history.replaceState(null, '', window.location.pathname + window.location.search);
    return { setup: status.setup_required, passwordlessDebug: 'passwordless_debug' in status && status.passwordless_debug === true, user: null };
  }
  if (!response.ok) throw new Error('无法读取登录状态');
  const user = parseUser(await response.json());
  sessionStorage.setItem(USER_KEY, JSON.stringify(user));
  return { setup: status.setup_required, passwordlessDebug: 'passwordless_debug' in status && status.passwordless_debug === true, user };
}

/**
 * 登录、注册普通用户或首次初始化管理员。
 * @param mode - 后端固定的账号操作。
 * @param username - 用户填写的账号名称。
 * @param password - 原始密码，仅通过请求提交。
 * @param setupToken - 服务器部署脚本生成的首次管理员初始化口令；其他模式省略。
 * @returns 已建立 Cookie 会话的账号。
 * @throws 后端拒绝或网络错误。
 */
export async function authenticate(mode: 'login' | 'register' | 'setup' | 'debug-login', username: string, password: string, setupToken = ''): Promise<AuthUser> {
  const user = parseUser(await authRequest(mode, mode === 'debug-login' ? { username } : { username, password }, mode === 'setup' ? setupToken : undefined));
  sessionStorage.setItem(USER_KEY, JSON.stringify(user));
  return user;
}

/**
 * 注销服务端会话后回到登录页，失败时保留页面供用户重试。
 * @returns 注销完成。
 * @throws 网络或后端错误。
 */
export async function logout(): Promise<void> {
  await authRequest('logout', {});
  sessionStorage.removeItem(USER_KEY);
  window.location.assign('/app/');
}


/**
 * 读取或切换开发免密码调试状态。
 * @param uid - 当前管理员编号。
 * @param enabled - 目标状态；省略时只读取。
 * @returns 后端实际启用状态。
 * @throws 请求失败或状态格式无效。
 */
export async function debugLoginSetting(uid: string, enabled?: boolean): Promise<boolean> {
  const response = await fetch(enabled === undefined ? '/api/auth/status' : `/api/users/${uid}/console/debug-login`, {
    credentials: 'same-origin', method: enabled === undefined ? 'GET' : 'PUT',
    headers: enabled === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: enabled === undefined ? undefined : JSON.stringify({ enabled }),
  });
  requireSession(response);
  if (!response.ok) throw new Error('无法更新免密码调试设置（仅管理员开发模式可用）');
  const data: unknown = await response.json();
  if (typeof data !== 'object' || data === null || !('passwordless_debug' in data)
    || typeof data.passwordless_debug !== 'boolean') throw new Error('调试状态格式非法');
  return data.passwordless_debug;
}
