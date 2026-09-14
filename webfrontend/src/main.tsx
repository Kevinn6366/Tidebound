import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './index.css';
import './theme-dark.css';
import App from './App';

const root = document.getElementById('root');
if (!root) throw new Error('页面缺少 React 挂载节点');
createRoot(root).render(<StrictMode><App /></StrictMode>);
