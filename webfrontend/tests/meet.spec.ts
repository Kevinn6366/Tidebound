import { randomUUID } from 'node:crypto';
import { expect, test } from '@playwright/test';

const greeting = '你来啦，今天也一起聊些有趣的事情吧。';

test.beforeEach(async ({ page }) => {
  const response = await page.request.post('/api/auth/register', {
    data: { username: `meet-${randomUUID()}`, password: 'test-user-password' },
  });
  expect(response.status()).toBe(201);
});

test('欢迎已后台完成，进入后逐字显示且刷新不重复生成', async ({ page }) => {
  await page.goto('/app/');
  await expect(page.getByRole('button', { name: 'START', exact: true })).toBeVisible();
  await expect.poll(async () => (await (await page.request.get('/api/chat/session')).json()).meet_run?.status).toBe('completed');
  const before = await (await page.request.get('/api/chat/session')).json();
  expect(before.messages).toHaveLength(1);
  expect(before.messages[0].role).toBe('assistant');
  expect(before.messages[0].created_at).toBeNull();
  expect(before.meet_run.display_started_at).toBeNull();
  await page.getByRole('button', { name: 'START', exact: true }).click();
  const reply = page.getByLabel('角色回复');
  await expect.poll(async () => (await reply.innerText()).length).toBeGreaterThan(0);
  expect((await reply.innerText()).length).toBeLessThan(greeting.length);
  await expect(reply).toHaveText(greeting);
  await expect.poll(async () => (await (await page.request.get('/api/chat/session')).json()).meet_run.display_started_at).not.toBeNull();
  const displayed = await (await page.request.get('/api/chat/session')).json();
  expect(Date.parse(displayed.meet_run.display_started_at)).toBeGreaterThan(Date.parse(before.meet_run.completed_at));
  await page.getByText('Log', { exact: true }).click();
  await expect(page.locator('time')).toHaveCount(1);
  await expect(page.locator('time')).toBeVisible();
  await expect(page.locator('time')).toHaveAttribute('datetime', displayed.meet_run.display_started_at);
  await page.screenshot({ path: 'test-results/meet-log.png', animations: 'disabled' });
  await page.reload();
  await expect(page.getByLabel('角色回复')).toHaveText(greeting);
  const after = await (await page.request.get('/api/chat/session')).json();
  expect(after.messages).toHaveLength(1);
  expect(after.meet_run.run_id).toBe(before.meet_run.run_id);
  expect(after.meet_run.display_started_at).toBe(displayed.meet_run.display_started_at);
});

test('进入时尚未生成，等待同一任务并恢复正常聊天', async ({ page }) => {
  await page.goto('/app/');
  await page.getByRole('button', { name: 'START', exact: true }).click();
  await expect(page.getByRole('status')).toHaveText('正在准备问候…');
  const input = page.getByPlaceholder(/输入/).first();
  await expect(input).toBeDisabled();
  await page.screenshot({ path: 'test-results/meet-waiting.png', animations: 'disabled' });
  await expect(page.getByLabel('角色回复')).toHaveText(greeting);
  await expect(input).toBeEnabled();
  await input.fill('我们聊聊天');
  await input.press('Enter');
  await expect(input).toHaveValue('');
  const after = await (await page.request.get('/api/chat/session')).json();
  expect(after.messages.map((message: { role: string }) => message.role)).toEqual(['assistant', 'user', 'assistant']);
  expect(after.meet_run).toBeNull();
});


test('停止欢迎后不提交，刷新不自动重试且可以显式重试', async ({ page }) => {
  await page.goto('/app/');
  await page.getByRole('button', { name: 'START', exact: true }).click();
  await expect(page.getByRole('status')).toHaveText('正在准备问候…');
  await page.getByRole('button', { name: '停止回复', exact: true }).click();
  await expect(page.getByRole('button', { name: '重试问候', exact: true })).toBeVisible();
  const stopped = await (await page.request.get('/api/chat/session')).json();
  expect(stopped.meet_run.status).toBe('stopped');
  expect(stopped.messages).toEqual([]);
  await page.reload();
  await expect(page.getByRole('button', { name: '重试问候', exact: true })).toBeVisible();
  const recovered = await (await page.request.get('/api/chat/session')).json();
  expect(recovered.meet_run.run_id).toBe(stopped.meet_run.run_id);
  expect(recovered.active_run).toBeNull();
  await page.getByRole('button', { name: '重试问候', exact: true }).click();
  await expect(page.getByLabel('角色回复')).toHaveText(greeting);
  const completed = await (await page.request.get('/api/chat/session')).json();
  expect(completed.messages).toHaveLength(1);
  expect(completed.meet_run.run_id).not.toBe(stopped.meet_run.run_id);
});


test('Dev 工具箱可重复运行欢迎工作流并写入历史', async ({ page }) => {
  await page.request.post('/api/auth/login', {
    data: { username: 'e2e-admin', password: 'test-admin-password' },
  });
  await page.goto('/app/');
  await page.getByRole('button', { name: 'START', exact: true }).click();
  const button = page.getByRole('complementary', { name: 'Dev 工具箱' })
    .getByRole('button', { name: '测试欢迎语', exact: true });
  await expect(button).toBeEnabled();
  const before = await (await page.request.get('/api/chat/session')).json();
  for (let index = 1; index <= 2; index++) {
    const submitted = page.waitForResponse('**/api/chat/meet/test');
    await button.click();
    expect((await submitted).status()).toBe(200);
    await expect(button).toBeDisabled();
    await expect(button).toBeEnabled();
    const after = await (await page.request.get('/api/chat/session')).json();
    expect(after.messages).toHaveLength(before.messages.length + index);
    expect(after.messages.at(-1).kind).toBe('meet');
    expect(after.messages.at(-1).role).toBe('assistant');
    expect(after.meet_run.run_id).not.toBe(before.meet_run?.run_id);
  }
  await page.screenshot({ path: 'test-results/dev-meet.png', animations: 'disabled' });
});
