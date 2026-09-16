import { randomUUID } from 'node:crypto';
import { readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, test } from '@playwright/test';

/** 使用真实页面圆环，输入来自独立实验的实际会话预算快照，不接触真实账号。 */
test('100-call experiment ring reflects measured before and after occupancy', async ({ page }) => {
  test.setTimeout(90_000);
  const root = process.env.COMPACTION_EXPERIMENT_DIR;
  test.skip(!root, 'Only run when an explicit experiment directory is supplied');
  const analysis = JSON.parse(readFileSync(resolve(root!, 'analysis.json'), 'utf8'));
  const manifest = JSON.parse(readFileSync(resolve(root!, 'manifest.json'), 'utf8'));
  const registered = await page.request.post('/api/auth/register', {
    data: { username: `ring-exp-${randomUUID()}`, password: 'synthetic-local-test-password' },
  });
  expect(registered.status()).toBe(201);
  let usage = { total: 32768, input_used: 0, output_reserved: manifest.main_output_reserved, format_margin: 1024 };
  await page.route('**/api/chat/session', route => route.fulfill({ json: {
    character: 'atri', character_name: '亚托莉', messages: [], active_run: null, tool_runs: [], context_usage: usage,
  } }));
  await page.goto('/app/');
  await page.getByRole('button', { name: 'START', exact: true }).click();
  const evidence: object[] = [];
  for (const scenario of manifest.scenarios) {
    const completed = analysis.trials.find((trial: { scenario: { key: string } }) => trial.scenario.key === scenario.key);
    const firstFile = readdirSync(resolve(root!, scenario.key, 'trials')).filter(name => name.endsWith('.json')).sort()[0];
    const trial = completed ?? JSON.parse(readFileSync(resolve(root!, scenario.key, 'trials', firstFile), 'utf8'));
    usage = { ...usage, total: scenario.budget, input_used: trial.before_input };
    await expect(page.locator('.context-budget > summary > span')).toHaveText(`${trial.before_ring_percent}%`);
    const before = await page.locator('.context-budget > summary > span').innerText();
    if (completed) usage = { ...usage, input_used: trial.ui_input };
    const expectedAfter = completed ? trial.after_ring_percent : trial.before_ring_percent;
    await expect(page.locator('.context-budget > summary > span')).toHaveText(`${expectedAfter}%`);
    const after = await page.locator('.context-budget > summary > span').innerText();
    await page.locator('.context-budget > summary').click();
    await page.locator('.context-budget').screenshot({ path: resolve(root!, `ring-${scenario.key}.png`) });
    await page.locator('.context-budget > summary').click();
    evidence.push({ group: scenario.key, episode: trial.episode, workflowStatus: trial.status, before, after,
      expectedAfter, matched: after === `${expectedAfter}%`, source: 'actual ContextBudgetRing component, isolated session route fixture' });
  }
  writeFileSync(resolve(root!, 'browser-ring-evidence.json'), JSON.stringify(evidence, null, 2));
});
