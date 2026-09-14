import { useCallback, useEffect, useState } from 'react';
import type { JSX } from 'react';
import AppCore from './gwc/AppCore.jsx';
import './gwc/utils/theme.js';

/**
 * 挂载恢复的完整上游界面；开发预览不假装登录为管理员。
 * @returns 原标题、对话框、全部设置和资源管理面板。
 */
export default function App(): JSX.Element {
  const [currentPage, setCurrentPage] = useState(window.location.hash.slice(1) || '/main');
  useEffect(() => {
    const update = (): void => setCurrentPage(window.location.hash.slice(1) || '/main');
    window.addEventListener('hashchange', update);
    return () => window.removeEventListener('hashchange', update);
  }, []);
  const navigate = useCallback((path: string): void => { window.location.hash = path; }, []);
  return <AppCore router={{ currentPage, navigate }} />;
}
