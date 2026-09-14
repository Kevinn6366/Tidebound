import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  use: { baseURL: 'http://127.0.0.1:5201', trace: 'retain-on-failure' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [{
    command: `${process.platform === 'win32' ? '..\\.venv\\Scripts\\python.exe' : '../.venv/bin/python'} -m uvicorn webapp.main:app --app-dir .. --host 127.0.0.1 --port 5201`,
    url: 'http://127.0.0.1:5201/api/health',
    reuseExistingServer: false,
  }, {
    command: 'npm run dev',
    url: 'http://127.0.0.1:5173/app/',
    reuseExistingServer: false,
  }],
});
