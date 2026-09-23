"""隔离浏览器测试数据与本地开发服务。"""
import os

from pydantic import SecretStr

from src.tidebound.config import AgentSettings
from src.tidebound.tools.companion import operations
from tests.support.account_store import FileUserStore
from webapp.auth.service import Credentials
from webapp.config import WebSettings
from webapp.main import create_app

settings = AgentSettings.from_env()
app = create_app(WebSettings(ui_data_dir=settings.data_dir / 'ui',
                             debug_log_path=settings.data_dir / 'agent-debug.log',
                             dev_frontend_origin=f"http://127.0.0.1:{os.environ.get('E2E_FRONTEND_PORT', '5174')}"), settings,
                 user_store=FileUserStore(settings.data_dir / 'auth' / 'users.json'))
if app.state.auth.setup_required:
    app.state.auth.create_user(Credentials(username="e2e-admin", password="test-admin-password"), setup=True)
settings.data_dir.mkdir(parents=True, exist_ok=True)
(settings.data_dir / 'agent-debug.log').write_text('[Agent] 模型调用\n[模型] 回复\n日志控制台测试输出\n', encoding='utf-8')


async def fixture_search(query: str, api_key: str) -> dict[str, object]:
    """仅在隔离E2E应用替换检索供应商，保留搜索工作流和真实模型HTTP协议。

    Args:
        query: 模型通过工具选择的搜索词。
        api_key: 测试占位凭据，不发送到外部。

    Returns:
        带已知事实的受控搜索材料。
    """
    return {'results': [{'title': '测试版本更新', 'url': 'https://example.com/release',
                         'description': '测试版本修复两个崩溃问题，新增导出功能。'}]}


if settings.model == 'protocol-fixture':
    operations.search_web = fixture_search
    app.state.chat.settings.search_api_key = SecretStr('e2e-placeholder')
