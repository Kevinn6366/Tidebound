import js from '@eslint/js';
import globals from 'globals';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';
import tseslint from 'typescript-eslint';
import { defineConfig, globalIgnores } from 'eslint/config';

export default defineConfig([
  globalIgnores(['dist', 'legacy', 'public/vendor', 'src/gwc/live2dcubismcore.js', 'test-results', 'playwright-report']),
  {
    // 保留的上游 JS 不在本轮整仓格式化；检查语法与未定义标识符，新增代码使用严格 TS。
    files: ['src/gwc/**/*.{js,jsx}'],
    languageOptions: { globals: globals.browser, parserOptions: { ecmaFeatures: { jsx: true } } },
    rules: { 'no-undef': 'error' },
  },
  { files: ['**/*.{ts,tsx}'], extends: [js.configs.recommended, tseslint.configs.recommended] },
  {
    files: ['src/**/*.{ts,tsx}'],
    extends: [reactHooks.configs.flat.recommended, reactRefresh.configs.vite],
    languageOptions: { globals: globals.browser },
  },
]);
