import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { defineConfig, devices } from '@playwright/test';

const runtimeDir = mkdtempSync(join(tmpdir(), 'tidebound-e2e-'));

export default defineConfig({
  testDir: './tests',
  use: { baseURL: 'http://127.0.0.1:5211', trace: 'retain-on-failure' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], channel: process.env.PLAYWRIGHT_CHROMIUM_CHANNEL } }],
  webServer: [{
    command: `${process.platform === 'win32' ? '..\\.venv\\Scripts\\python.exe' : '../.venv/bin/python'} -m uvicorn model_server:app --app-dir ../tests/support --host 127.0.0.1 --port 5212`,
    url: 'http://127.0.0.1:5212/health',
    reuseExistingServer: false,
  }, {
    command: `${process.platform === 'win32' ? '..\\.venv\\Scripts\\python.exe' : '../.venv/bin/python'} -m uvicorn e2e_app:app --app-dir ../tests/support --host 127.0.0.1 --port 5211`,
    env: { PYTHONPATH: '..', TIDEBOUND_MODE: 'dev', TIDEBOUND_DEBUG: 'false', TIDEBOUND_LLM_BASE_URL: 'http://127.0.0.1:5212/v1', TIDEBOUND_LLM_MODEL: 'protocol-fixture', TIDEBOUND_LLM_API_KEY: '', TIDEBOUND_AGENT_DATA_DIR: runtimeDir },
    url: 'http://127.0.0.1:5211/api/health',
    reuseExistingServer: false,
  }, {
    command: 'npm run dev -- --config vite.e2e.config.ts',
    url: 'http://127.0.0.1:5174/app/',
    reuseExistingServer: false,
  }],
});
