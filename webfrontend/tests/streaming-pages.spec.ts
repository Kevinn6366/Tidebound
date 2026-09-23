import { randomUUID } from 'node:crypto';
import { expect, test } from '@playwright/test';
import type { RunView, SessionView } from '../src/services/chatClient';

test('快速到达的多页续答逐页打完，完成状态不会截掉展示队列', async ({ page }) => {
  const registered = await page.request.post('/api/auth/register', {
    data: { username: `paging-${randomUUID()}`, password: 'test-user-password' },
  });
  const user = await registered.json();
  const first = '第一段需要完整显示。'.repeat(13);
  const second = '第二段也需要完整显示。'.repeat(13);
  const third = '最后一段。';
  const content = [first, second, third].join('\n');
  const run: RunView = {
    run_id: randomUUID(), kind: 'chat', created_at: new Date().toISOString(), completed_at: null,
    display_started_at: null, display_revision: 0, display_pending: false, context_usage: null,
    status: 'running', phase: 'generating', tools: [], preview: content, preview_stage: 'answer',
    user_content: '请继续说', reply: null, error: null,
  };
  let snapshot: SessionView = {
    timezone: 'Asia/Shanghai', meet_run: null, context_usage: null, character: 'atri',
    character_name: '亚托莉', messages: [], active_run: run, tool_runs: [],
  };
  await page.route('**/api/chat/meet', route => route.fulfill({ json: snapshot }));
  await page.route('**/api/chat/session', route => route.fulfill({ json: snapshot }));
  await page.route('**/api/chat/runs/*/events', route => route.fulfill({
    contentType: 'text/event-stream', body: `data: ${JSON.stringify(run)}\n\n`,
  }));
  await page.goto(`/app/${user.uid}#/chat`);
  const reply = page.getByLabel('角色回复', { exact: true });
  await expect(reply).toContainText('第一段');
  expect((await reply.innerText()).length).toBeLessThan(first.length);
  snapshot = { ...snapshot, active_run: null, messages: [{
    id: `${run.run_id}:assistant`, role: 'assistant', content, kind: 'chat',
    created_at: run.created_at, time_estimated: false, display_revision: 0, display_pending: false,
  }] };
  await expect(reply).toHaveText(first, { timeout: 10000 });
  await expect(reply).toHaveText(second, { timeout: 10000 });
  await expect(reply).toHaveText(third, { timeout: 10000 });
});
