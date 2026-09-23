"""验证硅基流动密钥的账号隔离、持久化与生产配置。"""

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from src.tidebound.config import AgentSettings
from src.tidebound.errors import AgentError
from src.tidebound.runtime.model_channels import SILICONFLOW_BASE_URL, SILICONFLOW_MODEL
from src.tidebound.runtime.session import ChatSession
from src.tidebound.runtime.types import Message, ModelReply
from src.tidebound.storage.model_credentials import ModelCredentialInput
from tests.support.account_store import FileUserStore
from webapp.config import WebSettings
from webapp.main import create_app


def test_account_model_key_is_private_and_survives_restart(tmp_path: Path) -> None:
    """不同账号仅能管理自己的密钥，API 只回传是否已配置。

    Args:
        tmp_path: 账号和运行文件的隔离测试目录。
    """
    settings = AgentSettings(mode='prod', data_dir=tmp_path / 'agent',
                             api_key=SecretStr('server-global-key'),
                             base_url='https://other.example/v1', model='other-model')
    users = FileUserStore(tmp_path / 'users.json')
    web = WebSettings(ui_data_dir=tmp_path / 'ui')
    app = create_app(web, settings, user_store=users)
    admin, other, anonymous = (TestClient(app) for _ in range(3))
    assert anonymous.get('/api/model-credential').status_code == 401
    assert admin.post('/api/auth/setup', json={'username': 'admin', 'password': 'test-password'}).status_code == 201
    assert other.post('/api/auth/register', json={'username': 'other', 'password': 'test-password'}).status_code == 201
    assert admin.get('/api/model-credential').json()['configured'] is False
    assert other.get('/api/model-credential').json()['configured'] is False
    owner_admin = app.state.auth.resolve(admin.cookies.get('tidebound_session')).scope
    owner_other = app.state.auth.resolve(other.cookies.get('tidebound_session')).scope
    assert app.state.chat.settings_for(owner_admin).api_key.get_secret_value() == ''
    key = 'sk-private-admin-12345678'
    response = admin.put('/api/model-credential', json={'api_key': key})
    assert response.status_code == 200
    assert response.json() == {'provider': 'siliconflow', 'configured': True,
                               'model': SILICONFLOW_MODEL, 'base_url': SILICONFLOW_BASE_URL}
    assert key not in response.text
    assert other.get('/api/model-credential').json()['configured'] is False
    assert app.state.chat.settings_for(owner_admin).api_key.get_secret_value() == key
    assert app.state.chat.settings_for(owner_other).api_key.get_secret_value() == ''
    assert app.state.chat.settings_for(owner_admin).model == SILICONFLOW_MODEL
    assert app.state.chat.settings_for(owner_admin).base_url == SILICONFLOW_BASE_URL
    saved = app.state.chat.model_credentials.path(owner_admin)
    assert saved.stat().st_mode & 0o777 == 0o600
    restarted = create_app(web, settings, user_store=FileUserStore(tmp_path / 'users.json'))
    assert restarted.state.chat.settings_for(owner_admin).api_key.get_secret_value() == key
    assert other.delete('/api/model-credential').status_code == 200
    assert admin.get('/api/model-credential').json()['configured'] is True
    assert admin.delete('/api/model-credential').json()['configured'] is False
    assert not saved.exists()


def test_prod_chat_runs_with_own_key(tmp_path: Path) -> None:
    """生产对话在账号配置后启动，并能提交模型替身的回复。

    Args:
        tmp_path: 独立的对话历史和密钥目录。
    """
    class ReplyModel:
        async def complete(self, system: str, messages: list[Message],
                           tools: list[dict[str, object]]) -> ModelReply:
            return ModelReply(message=Message(role='assistant', content='你好。'), finish_reason='stop')

    async def scenario() -> None:
        service = ChatSession(AgentSettings(mode='prod', data_dir=tmp_path), ReplyModel())
        owner = uuid4().hex
        with pytest.raises(AgentError, match='API Key'):
            service.start(owner, str(uuid4()), '你好')
        service.model_credentials.save(owner, ModelCredentialInput(api_key=SecretStr('sk-test-account-key')))
        run = service.start(owner, str(uuid4()), '你好')
        await service.active[owner].task
        assert run.status == 'completed'
        assert run.messages[-1].content == '你好。'
        await service.close()

    asyncio.run(scenario())
