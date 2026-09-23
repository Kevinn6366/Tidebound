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
  await page.goto(`http://127.0.0.1:${process.env.E2E_FRONTEND_PORT ?? 5174}/app/`);
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

test('上游双配音引擎设置可保存，未接入服务明确提示', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/app/');
  await page.getByRole('button', { name: 'SYSTEM', exact: true }).click();
  const status = page.waitForResponse('**/api/tts/qwen/status');
  await page.getByRole('button', { name: '声音设定', exact: true }).click();
  expect((await status).status()).toBe(501);
  await expect(page.getByRole('note')).toContainText('尚未接入 TTS');
  await page.getByText('开启全局 TTS 自动朗读', { exact: false }).locator('..').getByRole('button', { name: 'ON', exact: true }).click();
  await page.getByText('🎙️ 内置配音', { exact: false }).locator('..').getByRole('button', { name: 'ON', exact: true }).click();
  await expect(page.getByText('内置配音服务 (GPT-SoVITS)', { exact: true })).toBeVisible();
  await expect(page.getByText('服务不可用', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '扫描本机 GPT-SoVITS', exact: true })).toHaveCount(0);
  const saved = page.waitForResponse(response => response.url().endsWith('/core/live2d_settings_v35') && response.request().method() === 'PUT' && response.request().postDataJSON().ttsEngine === 'qwen');
  await page.getByRole('combobox', { name: '配音引擎' }).selectOption('qwen');
  expect((await saved).status()).toBe(200);
  await expect(page.getByText('内置配音服务 (Qwen3-TTS)', { exact: true })).toBeVisible();
  await expect(page.getByText('该后端功能尚未接入，原界面与配置已保留', { exact: true })).toBeVisible();
  await page.getByTitle('查看配置文档').click();
  await expect(page.getByText('📘 Qwen3-TTS 配置文档', { exact: true })).toBeVisible();
  await expect(page.getByText(/以下为上游 GWC-Pro 配置参考/)).toBeVisible();
  await page.reload();
  await page.getByRole('button', { name: 'SYSTEM', exact: true }).click();
  await page.getByRole('button', { name: '声音设定', exact: true }).click();
  await expect(page.getByRole('combobox', { name: '配音引擎' })).toHaveValue('qwen');
  await expect(page.getByText('服务不可用', { exact: true })).toBeVisible();
  expect(errors).toEqual([]);
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
  const previous = (await (await page.request.get('/api/chat/session')).json()).messages;
  await input.fill('等待测试');
  const submitted = page.waitForResponse('**/api/chat/messages');
  await input.press('Enter');
  expect((await submitted).status()).toBe(202);
  await page.getByRole('button', { name: '停止回复', exact: true }).click();
  await expect(page.getByText('本次回复已停止。', { exact: true })).toBeVisible();
  await expect(input).toBeEnabled();
  await expect(input).toHaveValue('等待测试');
  const session = await page.request.get('/api/chat/session');
  expect((await session.json()).messages).toEqual(previous);
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
  await expect.poll(async () => (await (await page.request.get('/api/chat/session')).json()).meet_run?.status).toBe('completed');
  const runId = randomUUID();
  expect((await page.request.post('/api/chat/messages', { data: { run_id: runId, content: '现在时间是什么' } })).status()).toBe(202);
  await expect.poll(async () => (await (await page.request.get(`/api/chat/runs/${runId}`)).json()).status).toBe('completed');
  await page.getByRole('link', { name: 'Console', exact: true }).click();
  await expect(page).toHaveURL(/\/app\/uid-00000001\/console$/);
  await expect(page.getByRole('heading', { name: '概览', exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: '查看完整 LLM 对话上下文' })).toBeVisible();
  await expect(page.getByLabel('运行日志', { exact: true })).toHaveCount(0);
  await page.getByRole('link', { name: '查看完整 LLM 对话上下文' }).click();
  await page.getByRole('button', { name: new RegExp(`现在时间是什么.*Run ${runId.slice(0, 8)}`) }).click();
  await expect(page.getByRole('navigation', { name: '本轮模型请求' }).getByRole('button', { name: /^主回复/ })).toHaveCount(2);
  await page.getByRole('button', { name: '主回复 · 第 1 次请求', exact: true }).click();
  await expect(page.getByLabel('本次请求注入')).toHaveCount(0);
  await page.getByText('原始请求 JSON（完整）', { exact: true }).click();
  await expect(page.getByLabel('完整模型请求正文')).toContainText('get_current_time');
  await expect(page.getByLabel('完整模型请求正文')).not.toContainText('先获取当前时间再回答');
  await page.getByRole('button', { name: '主回复 · 第 2 次请求', exact: true }).click();
  await expect(page.getByLabel('本次请求注入')).toContainText('本次实际附加到 system');
  await page.getByText('原始请求 JSON（完整）', { exact: true }).click();
  await expect(page.getByLabel('完整模型请求正文')).toContainText('先获取当前时间再回答');
  await page.screenshot({ path: 'test-results/console-context.png' });
  await page.getByRole('link', { name: '查看日志', exact: true }).click();
  await expect(page.getByLabel('完整模型请求正文')).toHaveCount(0);
  await page.getByRole('checkbox', { name: '原始终端日志' }).check();
  await expect(page.getByLabel('运行日志', { exact: true })).toContainText('日志控制台测试输出');
  await page.screenshot({ path: 'test-results/admin-console.png' });
  await page.reload();
  await page.getByRole('link', { name: '查看日志', exact: true }).click();
  await page.getByRole('checkbox', { name: '原始终端日志' }).check();
  await expect(page.getByLabel('运行日志', { exact: true })).toContainText('日志控制台测试输出');
});

test('普通用户界面不显示 console 且后端拒绝进入', async ({ page }) => {
  await page.goto('/app/');
  await expect(page.getByRole('button', { name: 'SYSTEM', exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Console', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '清空上下文', exact: true })).toHaveCount(0);
  await expect(page.getByRole('complementary', { name: 'Dev 工具箱' })).toHaveCount(0);
  expect((await page.request.post('/api/chat/context/reset')).status()).toBe(403);
  const me = await (await page.request.get('/api/auth/me')).json();
  expect((await page.request.get(`/app/${me.uid}/console`)).status()).toBe(403);
  await page.getByRole('button', { name: '退出登录', exact: true }).click();
  await expect(page.getByRole('button', { name: '登录', exact: true })).toBeVisible();
  expect((await page.request.get('/api/chat/session')).status()).toBe(401);
});

test('真实流式正文在执行结束前可见，刷新恢复且停止撤掉临时文字', async ({ page }) => {
  await page.goto('/app/');
  await page.getByRole('button', { name: 'START', exact: true }).click();
  const input = page.getByPlaceholder(/输入/).first();
  await expect(input).toBeEnabled();
  const previous = (await (await page.request.get('/api/chat/session')).json()).messages;
  await input.fill('流式测试');
  await input.press('Enter');
  const reply = page.getByLabel('角色回复', { exact: true });
  await expect(reply).toContainText('协议');
  const running = await (await page.request.get('/api/chat/session')).json();
  expect(running.active_run.status).toBe('running');
  expect(running.messages).toEqual(previous);
  const firstText = await reply.textContent();
  await expect.poll(async () => (await reply.textContent())?.length ?? 0).toBeGreaterThan(firstText?.length ?? 0);
  await page.reload();
  await expect(page.getByLabel('角色回复', { exact: true })).toContainText('协议');
  await page.getByRole('button', { name: '停止回复', exact: true }).click();
  await expect.poll(async () => (await (await page.request.get('/api/chat/session')).json()).active_run).toBeNull();
  await expect(page.getByLabel('角色回复', { exact: true })).toHaveText(previous.at(-1).content);
  expect((await (await page.request.get('/api/chat/session')).json()).messages).toEqual(previous);
});

test('底部预算圆环替换工作和备忘并展示真实请求用量', async ({ page }) => {
  await page.goto('/app/');
  await page.getByRole('button', { name: 'START', exact: true }).click();
  await expect(page.getByText('备忘', { exact: true })).toHaveCount(0);
  await expect(page.getByText(/^工作:(开|关)$/)).toHaveCount(0);
  const ring = page.locator('.context-budget > summary');
  await expect(page.getByPlaceholder(/输入/).first()).toBeEnabled();
  const welcomeUsage = (await (await page.request.get('/api/chat/session')).json()).context_usage;
  const welcomePercent = Math.min(100, Math.round((welcomeUsage.input_used + welcomeUsage.output_reserved + welcomeUsage.format_margin) / welcomeUsage.total * 100));
  await expect(ring).toHaveAttribute('aria-label', `上下文预算已占用 ${welcomePercent}%`);
  await ring.click();
  await expect(page.getByRole('region', { name: '上下文预算明细' })).toContainText('回复预留');
  await ring.click();
  const input = page.getByPlaceholder(/输入/).first();
  await expect(input).toBeEnabled();
  await input.fill('现在几点');
  await input.press('Enter');
  await expect(input).toHaveValue('');
  const snapshot = await (await page.request.get('/api/chat/session')).json();
  const usage = snapshot.context_usage;
  const percent = Math.min(100, Math.round((usage.input_used + usage.output_reserved + usage.format_margin) / usage.total * 100));
  await expect(ring).toHaveAttribute('aria-label', `上下文预算已占用 ${percent}%`);
  await ring.click();
  await expect(page.getByRole('region', { name: '上下文预算明细' })).toContainText(usage.input_used.toLocaleString());
  await page.screenshot({ path: 'test-results/context-budget-ring.png' });
});

test('管理员清空上下文后恢复初始状态且新请求不带旧历史', async ({ page }) => {
  await page.request.post('/api/auth/logout');
  await page.request.post('/api/auth/login', { data: { username: 'e2e-admin', password: 'test-admin-password' } });
  await page.goto('/app/');
  await page.getByRole('button', { name: 'START', exact: true }).click();
  const input = page.getByPlaceholder(/输入/).first();
  await expect(input).toBeEnabled();
  await input.fill('流式测试');
  const submitted = page.waitForResponse('**/api/chat/messages');
  await input.press('Enter');
  const oldRun = (await (await submitted).json()).run_id;
  await expect(page.getByLabel('角色回复', { exact: true })).toContainText('协议');
  await expect(page.getByRole('complementary', { name: 'Dev 工具箱' })).toBeVisible();
  await page.screenshot({ path: 'test-results/dev-toolbox.png' });
  await page.getByRole('complementary', { name: 'Dev 工具箱' }).getByRole('button', { name: '清空上下文', exact: true }).click();
  await expect.poll(async () => (await (await page.request.get('/api/chat/session')).json()).messages).toEqual([]);
  expect((await (await page.request.get('/api/chat/session')).json()).messages).toEqual([]);
  await expect(page.getByLabel('角色回复', { exact: true })).toHaveCount(0);
  await expect(page.locator('.context-budget > summary')).toHaveAttribute('aria-label', '上下文预算：尚无请求用量');
  await input.fill('重置后的全新问题');
  const newSubmission = page.waitForResponse('**/api/chat/messages');
  await input.press('Enter');
  const newRun = (await (await newSubmission).json()).run_id;
  await expect(input).toHaveValue('');
  const groups = await (await page.request.get('/api/users/uid-00000001/console/request-runs')).json();
  expect(groups.some((group: { run_id: string }) => group.run_id === oldRun)).toBe(true);
  const group = groups.find((item: { run_id: string }) => item.run_id === newRun);
  const snapshot = await (await page.request.get(`/api/users/uid-00000001/console/requests/${group.requests[0].request_id}`)).json();
  expect(snapshot.body.messages.map((message: { role: string }) => message.role)).toEqual(['system', 'user']);
});

for (const surface of ['聊天', 'Console']) {
  test(`${surface} 会话失效收到 HTTP 401 后跳转登录`, async ({ page }) => {
    if (surface === 'Console') {
      await page.request.post('/api/auth/login', { data: { username: 'e2e-admin', password: 'test-admin-password' } });
      await page.goto('/app/uid-00000001/console');
      await page.getByRole('link', { name: '查看日志', exact: true }).click();
    } else {
      await page.goto('/app/');
      await page.getByRole('button', { name: 'START', exact: true }).click();
      await expect(page.getByPlaceholder(/输入/).first()).toBeEnabled();
    }
    const oldUrl = page.url();
    const unauthorized = page.waitForResponse(response => response.status() === 401);
    await page.request.post('/api/auth/logout');
    await unauthorized;
    await expect(page).toHaveURL(/\/app\/$/);
    await expect(page.getByRole('heading', { name: '登录', exact: true })).toBeVisible();
    expect(await page.evaluate(() => sessionStorage.getItem('tidebound_user'))).toBeNull();
    await page.goto(oldUrl);
    await expect(page).toHaveURL(/\/app\/$/);
    await page.getByLabel('用户名', { exact: true }).fill('e2e-admin');
    await page.getByLabel('密码', { exact: true }).fill('wrong-password');
    await page.getByRole('button', { name: '登录', exact: true }).click();
    await expect(page.getByRole('alert')).toBeVisible();
    await expect(page).toHaveURL(/\/app\/$/);
  });
}

test('联网开关随下一条消息提交，关闭后撤销下一轮权限', async ({ page }) => {
  await page.goto('/app/');
  await page.getByRole('button', { name: 'START', exact: true }).click();
  const input = page.getByPlaceholder(/输入/).first();
  await expect(input).toBeEnabled();
  await page.getByRole('button', { name: '联网:关', exact: true }).click();
  await expect(page.getByRole('button', { name: '联网:开', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await input.fill('联网开启测试');
  const enabled = page.waitForRequest(request => request.url().endsWith('/api/chat/messages'));
  await input.press('Enter');
  const enabledRequest = await enabled;
  expect(enabledRequest.postDataJSON().internet_enabled).toBe(true);
  const enabledResponse = await enabledRequest.response();
  expect(enabledResponse?.status()).toBe(202);
  const enabledRun = await enabledResponse!.json();
  await expect.poll(async () => (await (await page.request.get(`/api/chat/runs/${enabledRun.run_id}`)).json()).status).toBe('completed');
  await expect(input).toBeEnabled();
  await page.getByRole('button', { name: '联网:开', exact: true }).click();
  await input.fill('联网关闭测试');
  const disabled = page.waitForRequest(request => request.url().endsWith('/api/chat/messages'));
  await input.press('Enter');
  const disabledRequest = await disabled;
  expect(disabledRequest.postDataJSON().internet_enabled).toBe(false);
  const disabledResponse = await disabledRequest.response();
  expect(disabledResponse?.status()).toBe(202);
  const disabledRun = await disabledResponse!.json();
  await expect.poll(async () => (await (await page.request.get(`/api/chat/runs/${disabledRun.run_id}`)).json()).status).toBe('completed');
});
