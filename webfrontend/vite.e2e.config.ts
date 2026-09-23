import { defineConfig, mergeConfig } from 'vite';
import baseConfig from './vite.config.ts';

export default mergeConfig(baseConfig, defineConfig({
  server: { port: Number(process.env.E2E_FRONTEND_PORT ?? 5174), proxy: { '/api': `http://127.0.0.1:${process.env.E2E_APP_PORT ?? 5211}`, '/models': `http://127.0.0.1:${process.env.E2E_APP_PORT ?? 5211}` } },
}));
