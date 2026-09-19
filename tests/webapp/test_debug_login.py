"""免密码调试的权限、普通账号创建及关闭撤销验证。"""
from pathlib import Path

from fastapi.testclient import TestClient

from tests.webapp.test_auth_console import CREDENTIALS, make_app


def test_debug_login_creation_and_revocation(tmp_path: Path) -> None:
    """管理员开启后用户名登录，关闭撤销，普通用户不能改开关。"""
    app = make_app(tmp_path)
    admin, guest, stranger = (TestClient(app) for _ in range(3))
    uid = admin.post('/api/auth/setup', json=CREDENTIALS).json()['uid']
    url = f'/api/users/{uid}/console/debug-login'
    assert guest.post('/api/auth/debug-login', json={'username': 'new-user'}).status_code == 403
    assert stranger.put(url, json={'enabled': True}).status_code == 401
    assert admin.put(url, json={'enabled': 'true'}).status_code == 422
    assert admin.put(url, json={'enabled': True}).json()['passwordless_debug'] is True
    result = guest.post('/api/auth/debug-login', json={'username': 'new-user'})
    assert result.status_code == 200
    assert result.json()['role'] == 'user'
    new_uid = result.json()['uid']
    assert guest.post('/api/auth/debug-login', json={'username': 'NEW-USER'}).json()['uid'] == new_uid
    assert guest.put(f'/api/users/{new_uid}/console/debug-login', json={'enabled': False}).status_code == 403
    assert stranger.post('/api/auth/debug-login', json={'username': 'new-admin', 'role': 'admin'}).status_code == 422
    assert stranger.post('/api/auth/debug-login', json={'username': CREDENTIALS['username']}).status_code == 200
    assert admin.put(url, json={'enabled': False}).status_code == 200
    assert guest.get('/api/auth/me').status_code == 401
    assert stranger.get('/api/auth/me').status_code == 401
    assert admin.get('/api/auth/me').status_code == 200
    assert guest.post('/api/auth/login', json=CREDENTIALS).status_code == 200
    assert make_app(tmp_path).state.auth.passwordless_debug is False


def test_production_rejects_debug_login(tmp_path: Path) -> None:
    """非开发模式不能开启或调用免密码入口。"""
    app = make_app(tmp_path)
    client = TestClient(app)
    uid = client.post('/api/auth/setup', json=CREDENTIALS).json()['uid']
    app.state.auth.development = False
    assert client.put(f'/api/users/{uid}/console/debug-login', json={'enabled': True}).status_code == 403
    assert client.post('/api/auth/debug-login', json={'username': CREDENTIALS['username']}).status_code == 403


def test_debug_login_persists_enabled_and_disabled(tmp_path: Path) -> None:
    """开发重启保持开关，关闭后重启不恢复，生产忽略已保存开启状态。"""
    from webapp.auth.service import AuthService

    app = make_app(tmp_path)
    admin = TestClient(app)
    uid = admin.post('/api/auth/setup', json=CREDENTIALS).json()['uid']
    endpoint = f'/api/users/{uid}/console/debug-login'
    assert admin.put(endpoint, json={'enabled': True}).status_code == 200
    restarted = make_app(tmp_path)
    fresh = TestClient(restarted)
    assert fresh.get('/api/auth/status').json()['passwordless_debug'] is True
    assert fresh.post('/api/auth/debug-login', json={'username': CREDENTIALS['username']}).status_code == 200
    production = AuthService(restarted.state.auth.store, development=False,
                             debug_state_path=restarted.state.auth.debug_state_path)
    assert production.passwordless_debug is False
    assert fresh.put(endpoint, json={'enabled': False}).status_code == 200
    assert make_app(tmp_path).state.auth.passwordless_debug is False
