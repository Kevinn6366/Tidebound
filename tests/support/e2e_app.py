"""隔离浏览器测试数据与本地开发服务。"""
from src.config import AgentSettings
from webapp.config import WebSettings
from webapp.main import create_app

settings = AgentSettings.from_env()
app = create_app(WebSettings(ui_data_dir=settings.data_dir / 'ui', dev_frontend_origin='http://127.0.0.1:5174'), settings)
