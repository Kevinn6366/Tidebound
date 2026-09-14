import { defineConfig, mergeConfig } from 'vite';
import baseConfig from './vite.config.ts';

export default mergeConfig(baseConfig, defineConfig({
  server: { port: 5174, proxy: { '/api': 'http://127.0.0.1:5211', '/models': 'http://127.0.0.1:5211' } },
}));
