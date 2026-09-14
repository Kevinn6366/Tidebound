import { readFileSync } from 'node:fs';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

// 产品版本统一维护在仓库根目录，构建时注入，避免界面独立维护版本号。
const appVersion = readFileSync(new URL('../VERSION', import.meta.url), 'utf8').trim();

export default defineConfig({
  base: '/app/',
  define: { 'import.meta.env.VITE_APP_VERSION': JSON.stringify(appVersion) },
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': 'http://127.0.0.1:5201',
      '/models': 'http://127.0.0.1:5201',
    },
  },
});
