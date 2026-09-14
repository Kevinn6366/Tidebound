import { randomUUID } from 'node:crypto';
import { expect, test } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  const result = await page.request.post('/api/auth/register', {
    data: { username: `test-${randomUUID()}`, password: 'test-user-password' },
  });
  expect(result.status()).toBe(201);
});

test('完整原界面启动，全部设置页签保留', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/app/');
  await expect(page.getByRole('button', { name: 'SYSTEM', exact: true })).toBeVisible();
  await page.screenshot({ path: 'test-results/restored-title.png' });
  await page.getByRole('button', { name: 'SYSTEM', exact: true }).click();
  for (const name of ['视觉设定', '文本互动', '声音设定', '剧本角色', '模型接口', '数据管理', '插件模组', '技能控制台', '知识库', '账号安全', '登录定制', '关于系统']) {
    await expect(page.getByRole('button', { name, exact: true })).toBeVisible();
    await page.getByRole('button', { name, exact: true }).click();
  }
  await page.getByRole('button', { name: '视觉设定', exact: true }).click();
  await page.screenshot({ path: 'test-results/restored-settings.png' });
  expect(errors).toEqual([]);
});

test('首版拒绝附件，失败保留草稿和附件', async ({ page }) => {
  await page.goto('/app/');
  await page.getByRole('button', { name: 'START', exact: true }).click();
  await page.screenshot({ path: 'test-results/restored-chat.png', animations: 'disabled' });
  const input = page.getByPlaceholder(/输入/).first();
  await expect(input).toBeEnabled();
  await input.fill('迁移后的对话测试');
  await page.locator('input[accept="image/*,.txt,.md,.json,.csv"]').setInputFiles({ name: 'note.txt', mimeType: 'text/plain', buffer: Buffer.from('附件测试') });
  await expect(page.getByText('note.txt', { exact: true })).toBeVisible();
  const responsePromise = page.waitForResponse('**/api/chat/messages');
  await input.press('Enter');
  const response = await responsePromise;
  expect(response.status()).toBe(422);
  expect(response.request().postDataJSON().content).toBe('迁移后的对话测试');
  expect(response.request().postDataJSON().attachments).toEqual([{ type: 'document', name: 'note.txt', data: '附件测试' }]);
  await expect(page.getByText(/v0.01 暂时只支持文字/)).toBeVisible();
  await expect(input).toHaveValue('迁移后的对话测试');
  await expect(page.getByText('note.txt', { exact: true })).toBeVisible();
});

test('开发模式仍可访问原完整设置', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('http://127.0.0.1:5174/app/');
  await page.getByRole('button', { name: 'SYSTEM', exact: true }).click();
  await expect(page.getByRole('button', { name: '文本互动', exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});

test('原文本设置可以保存并在刷新后恢复', async ({ page }) => {
  await page.goto('/app/');
  await page.getByRole('button', { name: 'SYSTEM', exact: true }).click();
  await page.getByRole('button', { name: '文本互动', exact: true }).click();
  const saved = page.waitForResponse(response => response.url().endsWith('/core/live2d_settings_v35') && response.request().method() === 'PUT' && response.request().postDataJSON().dialogOpacity === 0.85);
  await page.getByRole('slider', { name: '主对话框不透明度', exact: true }).fill('0.85');
  expect((await saved).status()).toBe(200);
  await page.reload();
  await page.getByRole('button', { name: 'SYSTEM', exact: true }).click();
  await page.getByRole('button', { name: '文本互动', exact: true }).click();
  await expect(page.getByRole('slider', { name: '主对话框不透明度', exact: true })).toHaveValue('0.85');
});

test('原背景上传和备份导出功能可用', async ({ page }) => {
  await page.addInitScript(() => { Object.defineProperty(window, 'showSaveFilePicker', { value: undefined }); });
  await page.goto('/app/');
  await page.getByRole('button', { name: 'SYSTEM', exact: true }).click();
  const upload = page.getByLabel('导入游戏背景图', { exact: true });
  const saved = page.waitForResponse(response => response.request().method() === 'POST' && /\/api\/userdata\/uid-\d{8}\/(bg_images|app_image)/.test(response.url()));
  await upload.setInputFiles({ name: 'test-background.png', mimeType: 'image/png', buffer: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aS9sAAAAASUVORK5CYII=', 'base64') });
  expect((await saved).status()).toBe(200);
  await page.getByRole('button', { name: '数据管理', exact: true }).click();
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: '备份当前用户数据', exact: true }).click();
  expect((await download).suggestedFilename()).toMatch(/\.zip$/);
});


test('时间工具闭环、历史刷新及固定角色', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/app/');
  await page.getByRole('button', { name: 'START', exact: true }).click();
  const input = page.getByPlaceholder(/输入/).first();
  await expect(input).toBeEnabled();
  await input.fill('现在几点了？');
  await input.press('Enter');
  await expect(input).toHaveValue('');
  await page.getByText('Log', { exact: true }).click();
  await expect(page.getByText(/协议测试：/).last()).toBeVisible();
  await page.getByText(/工具记录 · 已完成/).click();
  await expect(page.getByText('get_current_time', { exact: true })).toBeVisible();
  await expect(page.getByText(/结果：.*Asia\/Shanghai/)).toBeVisible();
  await page.screenshot({ path: 'test-results/agent-tools.png' });
  await page.reload();
  await page.getByText('Log', { exact: true }).click();
  await expect(page.getByText('现在几点了？', { exact: true })).toBeVisible();
  await expect(page.getByText(/工具记录 · 已完成/)).toHaveCount(1);
  expect(errors).toEqual([]);
});

test('停止回复后不提交本轮，仍能继续发送', async ({ page }) => {
  await page.goto('/app/');
  await page.getByRole('button', { name: 'START', exact: true }).click();
  const input = page.getByPlaceholder(/输入/).first();
  await expect(input).toBeEnabled();
  await input.fill('等待测试');
  const submitted = page.waitForResponse('**/api/chat/messages');
  await input.press('Enter');
  expect((await submitted).status()).toBe(202);
  await page.getByRole('button', { name: '停止回复', exact: true }).click();
  await expect(page.getByText('本次回复已停止。', { exact: true })).toBeVisible();
  await expect(input).toBeEnabled();
  await expect(input).toHaveValue('等待测试');
  const session = await page.request.get('/api/chat/session');
  expect((await session.json()).messages).toEqual([]);
  await input.fill('继续');
  await input.press('Enter');
  await expect(input).toHaveValue('');
});


test('管理员登录后在专属 console 持续读取日志', async ({ page }) => {
  await page.request.post('/api/auth/logout');
  await page.goto('/app/');
  await page.getByLabel('用户名', { exact: true }).fill('e2e-admin');
  await page.getByLabel('密码', { exact: true }).fill('test-admin-password');
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await expect(page).toHaveURL(/\/app\/uid-00000001$/);
  await page.getByRole('link', { name: 'Console', exact: true }).click();
  await expect(page).toHaveURL(/\/app\/uid-00000001\/console$/);
  await expect(page.getByRole('heading', { name: 'LLM 运行日志' })).toBeVisible();
  await expect(page.getByLabel('运行日志', { exact: true })).toContainText('日志控制台测试输出');
  await page.screenshot({ path: 'test-results/admin-console.png' });
  await page.reload();
  await expect(page.getByLabel('运行日志', { exact: true })).toContainText('日志控制台测试输出');
});

test('普通用户界面不显示 console 且后端拒绝进入', async ({ page }) => {
  await page.goto('/app/');
  await expect(page.getByRole('button', { name: 'SYSTEM', exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Console', exact: true })).toHaveCount(0);
  const me = await (await page.request.get('/api/auth/me')).json();
  expect((await page.request.get(`/app/${me.uid}/console`)).status()).toBe(403);
  await page.getByRole('button', { name: '退出登录', exact: true }).click();
  await expect(page.getByRole('button', { name: '登录', exact: true })).toBeVisible();
  expect((await page.request.get('/api/chat/session')).status()).toBe(401);
});
