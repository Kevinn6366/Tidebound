import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

interface AuditRequest { request_id: string; purpose: string }
interface AuditGroup { run_id: string; requests: AuditRequest[] }
interface AuditSnapshot { body: { messages: { role: string; content: string }[] } }

/** 查询指定轮次的真实模型请求审计，包含后台节点。
 * @param request - 当前已登录管理员的 HTTP 会话。
 * @param runId - 经聊天接口提交的轮次。
 * @returns 该轮次已记录的请求列表。
 */
async function audit(request: APIRequestContext, runId: string): Promise<AuditRequest[]> {
  const groups: AuditGroup[] = await (await request.get('/api/users/uid-00000001/console/request-runs')).json();
  return groups.find(group => group.run_id === runId)?.requests ?? [];
}

/** 从页面发送消息并等待真实后端成功提交。
 * @param page - 已进入聊天的浏览器页面。
 * @param content - 本场景的合成用户输入。
 * @returns 后端生成的轮次 ID。
 */
async function send(page: Page, content: string): Promise<string> {
  const input = page.getByPlaceholder(/输入/).first();
  await expect(input).toBeEnabled();
  await input.fill(content);
  const submitted = page.waitForResponse('**/api/chat/messages');
  await input.press('Enter');
  const response = await submitted;
  expect(response.ok()).toBeTruthy();
  const { run_id: id } = await response.json();
  await expect.poll(async () => (await (await page.request.get(`/api/chat/runs/${id}`)).json()).status,
    { timeout: 20000 }).toBe('completed');
  await expect(input).toBeEnabled();
  return id;
}

test.beforeEach(async ({ page }) => {
  expect((await page.request.post('/api/auth/login', { data: { username: 'e2e-admin', password: 'test-admin-password' } })).ok()).toBeTruthy();
  expect((await page.request.post('/api/chat/context/reset')).ok()).toBeTruthy();
  await page.goto('/app/');
  await page.getByRole('button', { name: 'START', exact: true }).click();
  await expect(page.getByPlaceholder(/输入/).first()).toBeEnabled();
});

test('长期摘要静默落盘、独立读取、跟进复用和清空隔离贯穿完整链路', async ({ page }) => {
  test.setTimeout(60000);
  const source = await send(page, '我们一起练习过面试，我周五参加复试。');
  await expect.poll(async () => (await audit(page.request, source)).some(item => item.purpose === 'memory.rolling_summary')).toBeTruthy();
  const read = await send(page, 'E2E读取摘要');
  await expect(page.getByLabel('角色回复', { exact: true })).toContainText('available');
  const followup = await send(page, 'E2E创建跟进：复试以后关心一下结果。');
  const requests = await audit(page.request, followup);
  const step = requests.find(item => item.purpose === 'workflow.followup');
  expect(step).toBeDefined();
  const snapshot: AuditSnapshot = await (await page.request.get(`/api/users/uid-00000001/console/requests/${step!.request_id}`)).json();
  const material = JSON.parse(snapshot.body.messages.find(message => message.role === 'user')!.content);
  expect(material.conversation_memory.status).toBe('available');
  expect(JSON.stringify(material.conversation_memory)).toContain('周五参加复试');
  const session = await (await page.request.get('/api/chat/session')).json();
  expect(session.messages.every((message: { content: string }) => !message.content.includes('"entries"'))).toBeTruthy();
  expect(session.tool_runs.some((run: { run_id: string }) => run.run_id === read)).toBeTruthy();
  await page.getByRole('complementary', { name: 'Dev 工具箱' }).getByRole('button', { name: '清空上下文', exact: true }).click();
  await expect.poll(async () => (await (await page.request.get('/api/chat/session')).json()).messages).toEqual([]);
  await send(page, 'E2E读取摘要');
  await expect(page.getByLabel('角色回复', { exact: true })).toContainText('not_generated');
  await page.screenshot({ path: 'test-results/rolling-summary-reset.png' });
});

test('联网首段和续答均完整展示，全部工作流节点进入真实审计', async ({ page }) => {
  test.setTimeout(60000);
  const online = page.getByRole('button', { name: '联网:关', exact: true });
  await online.click();
  const id = await send(page, 'E2E联网搜索：这次版本更新了什么？');
  const requests = await audit(page.request, id);
  const purposes = requests.map(item => item.purpose);
  for (const purpose of ['tools.websearch.reaction', 'tools.websearch.context', 'tools.websearch.impression', 'tools.websearch.delivery']) {
    expect(purposes).toContain(purpose);
  }
  const session = await (await page.request.get('/api/chat/session')).json();
  const texts = session.messages.filter((message: { role: string }) => message.role === 'assistant').map((message: { content: string }) => message.content);
  expect(texts).toContain('哼哼，让我看看这次有什么变化。');
  expect(texts).toContain('这次修好了两个会崩溃的问题，还加了导出功能。这个我倒是用得上。');
  await expect(page.getByLabel('角色回复', { exact: true })).toContainText('这个我倒是用得上');
  const step = requests.find(item => item.purpose === 'tools.websearch.reaction')!;
  const snapshot: AuditSnapshot = await (await page.request.get(`/api/users/uid-00000001/console/requests/${step.request_id}`)).json();
  expect(snapshot.body.messages[0].content).toContain('亚托莉');
  expect(snapshot.body.messages[0].content.length).toBeGreaterThan(2000);
  await page.screenshot({ path: 'test-results/search-complete.png' });
});
