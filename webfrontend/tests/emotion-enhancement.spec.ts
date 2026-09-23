import { expect, test } from '@playwright/test';

const path = '**/api/chat/emotion-enhancement';
const model = 'atri-instruct-fixture';

test.beforeEach(async ({ page }) => {
  const response = await page.request.post('/api/auth/login', {
    data: { username: 'e2e-admin', password: 'test-admin-password' },
  });
  expect(response.status()).toBe(200);
});

test('情感增强等待保存确认，失败保留原状态，刷新读取已保存状态', async ({ page }) => {
  let enabled = false;
  let rejectSave = true;
  let releaseSave!: () => void;
  const pendingSave = new Promise<void>(resolve => { releaseSave = resolve; });
  const writes: unknown[] = [];
  await page.route(path, async route => {
    if (route.request().method() === 'PUT') {
      const body: unknown = route.request().postDataJSON();
      writes.push(body);
      if (rejectSave) {
        rejectSave = false;
        await pendingSave;
        await route.fulfill({ status: 503, json: { detail: { message: '设置暂时无法保存，请重试' } } });
        return;
      }
      expect(body).toEqual({ enabled: true });
      enabled = true;
    }
    await route.fulfill({ json: { enabled, configured: true, model } });
  });
  await page.goto('/app/');
  await page.getByRole('button', { name: 'START', exact: true }).click();
  const toolbox = page.getByRole('complementary', { name: 'Dev 工具箱', exact: true });
  await expect(toolbox).toBeVisible();
  await expect(toolbox.getByText(/情感增强/)).toHaveCount(0);
  const toggle = page.getByRole('navigation', { name: '聊天菜单栏', exact: true })
    .getByRole('button', { name: '云端情感增强', exact: true });
  await expect(toggle).toHaveText('情感增强 · 关');
  await expect(toggle).toHaveAttribute('aria-pressed', 'false');
  await toggle.click();
  await expect(toggle).toHaveText('情感增强 · 保存中…');
  await expect(toggle).toBeDisabled();
  await expect(toggle).toHaveAttribute('aria-pressed', 'false');
  releaseSave();
  await expect(page.getByText('设置暂时无法保存，请重试', { exact: true })).toBeVisible();
  await expect(toggle).toHaveText('情感增强 · 关');
  await expect(toggle).toHaveAttribute('aria-pressed', 'false');
  await toggle.click();
  await expect(toggle).toHaveText('情感增强 · 开');
  await expect(toggle).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByText('情感增强已开启，下一轮对话生效', { exact: true })).toBeVisible();
  expect(writes).toEqual([{ enabled: true }, { enabled: true }]);
  await page.reload();
  await expect(toggle).toHaveText('情感增强 · 开');
  await expect(toggle).toHaveAttribute('aria-pressed', 'true');
});

test('云端未配置时不能开启，但已开启的账号仍可关闭', async ({ page }) => {
  let enabled = false;
  await page.route(path, async route => {
    if (route.request().method() === 'PUT') {
      expect(route.request().postDataJSON()).toEqual({ enabled: false });
      enabled = false;
    }
    await route.fulfill({ json: { enabled, configured: false, model } });
  });
  await page.goto('/app/');
  await page.getByRole('button', { name: 'START', exact: true }).click();
  const toggle = page.getByRole('navigation', { name: '聊天菜单栏', exact: true })
    .getByRole('button', { name: '云端情感增强', exact: true });
  await expect(toggle).toHaveAttribute('title', '云端模型尚未配置，暂时无法开启。');
  await expect(toggle).toHaveAttribute('aria-pressed', 'false');
  await expect(toggle).toBeDisabled();
  enabled = true;
  await page.reload();
  await expect(toggle).toHaveAttribute('aria-pressed', 'true');
  await expect(toggle).toBeEnabled();
  await toggle.click();
  await expect(page.getByText('情感增强已关闭，下一轮对话生效', { exact: true })).toBeVisible();
  await expect(toggle).toHaveAttribute('aria-pressed', 'false');
  await expect(toggle).toBeDisabled();
});

test('非法配置响应显示加载错误，重试后恢复操作', async ({ page }) => {
  let valid = false;
  await page.route(path, route => route.fulfill({
    json: valid ? { enabled: false, configured: true, model } : { enabled: 'false', configured: true, model },
  }));
  await page.goto('/app/');
  await page.getByRole('button', { name: 'START', exact: true }).click();
  const toggle = page.getByRole('navigation', { name: '聊天菜单栏', exact: true })
    .getByRole('button', { name: '云端情感增强', exact: true });
  await expect(page.getByText('情感增强配置格式非法', { exact: true })).toBeVisible();
  await expect(toggle).toHaveText('情感增强 · 重试');
  await expect(toggle).toHaveAttribute('title', '情感增强配置格式非法，点击重试');
  await expect(toggle).toBeEnabled();
  valid = true;
  await toggle.click();
  await expect(toggle).toHaveText('情感增强 · 关');
  await expect(toggle).toHaveAttribute('aria-pressed', 'false');
  await expect(toggle).toBeEnabled();
});
