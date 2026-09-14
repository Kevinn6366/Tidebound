"""隔离浏览器测试数据与本地开发服务。"""
from src.tidebound.config import AgentSettings
from tests.support.account_store import FileUserStore
from webapp.auth.service import Credentials
from webapp.config import WebSettings
from webapp.main import create_app

settings = AgentSettings.from_env()
app = create_app(WebSettings(ui_data_dir=settings.data_dir / 'ui',
                             debug_log_path=settings.data_dir / 'agent-debug.log',
                             dev_frontend_origin='http://127.0.0.1:5174'), settings,
                 user_store=FileUserStore(settings.data_dir / 'auth' / 'users.json'))
if app.state.auth.setup_required:
    app.state.auth.create_user(Credentials(username="e2e-admin", password="test-admin-password"), setup=True)
settings.data_dir.mkdir(parents=True, exist_ok=True)
(settings.data_dir / 'agent-debug.log').write_text('[Agent] 模型调用\n[模型] 回复\n日志控制台测试输出\n', encoding='utf-8')
