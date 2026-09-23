import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { defineConfig, devices } from '@playwright/test';

const appPort = process.env.E2E_APP_PORT ?? '5211';
const modelPort = process.env.E2E_MODEL_PORT ?? '5212';
const frontendPort = process.env.E2E_FRONTEND_PORT ?? '5174';
const runtimeDir = mkdtempSync(join(tmpdir(), 'tidebound-e2e-'));

export default defineConfig({
  testDir: './tests',
  use: { baseURL: `http://127.0.0.1:${appPort}`, trace: 'retain-on-failure' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], channel: process.env.PLAYWRIGHT_CHROMIUM_CHANNEL } }],
  webServer: [{
    command: `${process.platform === 'win32' ? '..\\.venv\\Scripts\\python.exe' : '../.venv/bin/python'} -m uvicorn model_server:app --app-dir ../tests/support --host 127.0.0.1 --port ${modelPort}`,
    url: `http://127.0.0.1:${modelPort}/health`,
    reuseExistingServer: false,
  }, {
    command: `${process.platform === 'win32' ? '..\\.venv\\Scripts\\python.exe' : '../.venv/bin/python'} -m uvicorn e2e_app:app --app-dir ../tests/support --host 127.0.0.1 --port ${appPort}`,
    env: { PYTHONPATH: '..', TIDEBOUND_MODE: 'dev', TIDEBOUND_DEBUG: 'false', TIDEBOUND_LLM_BASE_URL: `http://127.0.0.1:${modelPort}/v1`, TIDEBOUND_LLM_MODEL: 'protocol-fixture', TIDEBOUND_LLM_API_KEY: '', TIDEBOUND_AGENT_DATA_DIR: runtimeDir, E2E_FRONTEND_PORT: frontendPort, TIDEBOUND_MEET_BASE_URL: `http://127.0.0.1:${modelPort}/v1`, TIDEBOUND_WEBSEARCH_BASE_URL: `http://127.0.0.1:${modelPort}/v1`, TIDEBOUND_CONTEXT_LIMIT: '65536', TIDEBOUND_ROLLING_SUMMARY_DELAY_SECONDS: '0.1' },
    url: `http://127.0.0.1:${appPort}/api/health`,
    reuseExistingServer: false,
  }, {
    command: 'npm run dev -- --config vite.e2e.config.ts',
    env: { E2E_APP_PORT: appPort, E2E_FRONTEND_PORT: frontendPort },
    url: `http://127.0.0.1:${frontendPort}/app/`,
    reuseExistingServer: false,
  }],
});
