"""管理员渠道接口的权限、配置与凭据边界。"""
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import SecretStr

from tests.webapp.test_auth_console import CREDENTIALS, make_app


def test_console_channels_auth_and_configuration(tmp_path: Path) -> None:
    """普通账号不能切换，空 Key 不可选，完整配置可保存且不回传密钥。

    Args:
        tmp_path: 隔离账号和配置目录。
    """
    app = make_app(tmp_path)
    admin, user, anonymous = (TestClient(app) for _ in range(3))
    uid = admin.post('/api/auth/setup', json=CREDENTIALS).json()['uid']
    user_uid = user.post('/api/auth/register', json={'username': 'other', 'password': 'test-password'}).json()['uid']
    url = f'/api/users/{uid}/console/model-channels'
    payload = {'channel': 'codex789'}
    assert anonymous.get(url).status_code == 401
    assert user.put(f'/api/users/{user_uid}/console/model-channels', json=payload).status_code == 403
    assert admin.put(f'/api/users/{user_uid}/console/model-channels', json=payload).status_code == 403
    assert admin.put(url, json={'channel': 'unknown'}).status_code == 422
    assert admin.put(url, json={**payload, 'api_key': 'override'}).status_code == 422
    assert admin.put(url, json=payload).status_code == 409
    assert admin.get(url).json()['selected'] == 'siliconflow'
    app.state.chat.settings.relay_api_key = SecretStr('private-test-key')
    result = admin.put(url, json=payload)
    assert result.status_code == 200
    assert result.json()['selected'] == 'codex789'
    assert 'private-test-key' not in result.text
    assert 'api_key' not in result.text
    assert admin.get(url).json()['selected'] == 'codex789'
