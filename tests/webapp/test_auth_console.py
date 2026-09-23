"""验证账号持久化、角色、归属和固定日志文件的读取边界。"""

import time
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.tidebound.config import AgentSettings
from src.tidebound.runtime.types import Message, RunRecord
from tests.support.account_store import FileUserStore
from webapp.config import WebSettings
from webapp.main import create_app

CREDENTIALS = {"username": "admin", "password": "test-password"}


def make_app(root: Path) -> FastAPI:
    """组装隔离账号、日志和静态页面的测试应用。

    Args:
        root: pytest 临时目录。

    Returns:
        测试 FastAPI 应用。
    """
    dist = root / "dist"
    dist.mkdir(exist_ok=True)
    (dist / "index.html").write_text("<html>Tidebound</html>")
    return create_app(WebSettings(frontend_dist=dist, ui_data_dir=root / "ui",
                                  debug_log_path=root / "agent-debug.log"), AgentSettings(data_dir=root / "agent"), user_store=FileUserStore(root / "auth" / "users.json"))


def test_user_roles_and_console_boundaries(tmp_path: Path) -> None:
    """真实 Cookie 鉴权不能被 UID、角色参数或旧预览 Cookie 绕过。

    Args:
        tmp_path: 隔离测试目录。
    """
    app = make_app(tmp_path)
    admin, user, anonymous = (TestClient(app) for _ in range(3))
    assert anonymous.get('/api/chat/session').status_code == 401
    assert anonymous.get('/app/uid-00000001/console', follow_redirects=False).headers['location'] == '/app/'
    result = admin.post('/api/auth/setup', json=CREDENTIALS)
    assert result.status_code == 201
    assert result.json() == {"uid": "uid-00000001", "username": "admin", "role": "admin"}
    assert 'HttpOnly' in result.headers['set-cookie']
    assert 'SameSite=strict' in result.headers['set-cookie']
    assert admin.post('/api/auth/setup', json=CREDENTIALS).status_code == 409
    assert user.post('/api/auth/register', json=CREDENTIALS | {"username": "ordinary", "role": "admin"}).status_code == 422
    result = user.post('/api/auth/register', json=CREDENTIALS | {"username": "ordinary"})
    assert result.json()['uid'] == 'uid-00000002'
    assert result.json()['role'] == 'user'
    assert user.get('/app/uid-00000002').status_code == 200
    assert user.get('/app/uid-00000002/console').status_code == 403
    assert user.get('/app/uid-00000001/console').status_code == 403
    assert user.get('/api/users/uid-00000001/console/log').status_code == 403
    assert admin.get('/api/users/uid-00000002/console/log').status_code == 403
    assert admin.get('/app/uid-00000001/console').status_code == 200
    assert admin.get('/app/uid-00000002').status_code == 403
    assert admin.get('/app/', follow_redirects=False).headers['location'] == '/app/uid-00000001'
    assert user.get('/admin/api/skills').status_code == 403
    assert admin.get('/api/chat/session', headers={'X-Tidebound-Uid': 'uid-00000002'}).status_code == 403
    anonymous.cookies.set('tidebound_preview', uuid4().hex)
    assert anonymous.get('/api/chat/session').status_code == 401
    anonymous.cookies.set('tidebound_session', 'forged')
    assert anonymous.get('/api/auth/me').status_code == 401


def test_persisted_account_login_expiry_and_logout(tmp_path: Path) -> None:
    """密码使用哈希持久化；重启、过期与注销撤销会话。

    Args:
        tmp_path: 隔离测试目录。
    """
    app = make_app(tmp_path)
    client = TestClient(app)
    client.post('/api/auth/setup', json=CREDENTIALS)
    token = client.cookies.get('tidebound_session')
    saved = (tmp_path / 'auth' / 'users.json').read_text()
    assert CREDENTIALS['password'] not in saved
    assert 'password_hash' in saved
    assert client.post('/api/auth/login', json=CREDENTIALS | {'password': 'wrong-password'}).status_code == 401
    app.state.auth.sessions[token].expires_at = time.time() - 1
    assert client.get('/api/auth/me').status_code == 401
    assert client.post('/api/auth/login', json=CREDENTIALS).status_code == 200
    token = client.cookies.get('tidebound_session')
    assert client.post('/api/auth/logout').status_code == 200
    assert client.get('/api/auth/me').status_code == 401
    client.cookies.set('tidebound_session', token)
    assert client.get('/api/auth/me').status_code == 401
    restarted = TestClient(make_app(tmp_path))
    assert restarted.post('/api/auth/login', json=CREDENTIALS).json()['uid'] == 'uid-00000001'


def test_chat_and_settings_follow_account_across_browsers(tmp_path: Path) -> None:
    """相同账号共享已持久化历史，普通账号不能读取或停止其他账号的执行。

    Args:
        tmp_path: 隔离测试目录。
    """
    app = make_app(tmp_path)
    admin, other, same = (TestClient(app) for _ in range(3))
    admin.post('/api/auth/setup', json=CREDENTIALS)
    other.post('/api/auth/register', json=CREDENTIALS | {'username': 'other'})
    same.post('/api/auth/login', json=CREDENTIALS)
    scope = app.state.auth.resolve(admin.cookies.get('tidebound_session')).scope
    run_id = str(uuid4())
    app.state.chat.store.save(scope, RunRecord(run_id=run_id, created_at='2026-09-14T00:00:00Z', status='completed',
        user_content='private', messages=[Message(role='user', content='private'), Message(role='assistant', content='reply')]))
    assert same.get('/api/chat/session').json()['messages'][0]['content'] == 'private'
    assert other.get('/api/chat/session').json()['messages'] == []
    assert other.get(f'/api/chat/runs/{run_id}').status_code == 404
    assert other.get(f'/api/chat/runs/{run_id}/events').status_code == 404
    assert other.post(f'/api/chat/runs/{run_id}/stop').status_code == 404
    path = '/api/userdata/uid-00000001/core/settings'
    assert admin.put(path, json={'value': 1}).status_code == 200
    assert same.get(path).json() == {'value': 1}
    assert other.get(path).status_code == 403
    assert other.get('/api/userdata/uid-00000002/core/settings').json() is None


def test_console_tail_append_rotation_and_limit(tmp_path: Path) -> None:
    """日志按固定路径读取末尾 100 行，支持追加、替换及有界长行。

    Args:
        tmp_path: 隔离日志目录。
    """
    client = TestClient(make_app(tmp_path))
    client.post('/api/auth/setup', json=CREDENTIALS)
    endpoint = '/api/users/uid-00000001/console/log'
    assert client.get(endpoint).json()['exists'] is False
    log = tmp_path / 'agent-debug.log'
    log.write_text(''.join(f'日志 {index}\n' for index in range(120)), encoding='utf-8')
    response = client.get(endpoint)
    assert response.headers['cache-control'] == 'no-store'
    assert response.json()['content'].splitlines() == [f'日志 {index}' for index in range(20, 120)]
    with log.open('a') as output:
        output.write('新增模型输出\n')
    assert client.get(endpoint).json()['content'].endswith('新增模型输出\n')
    log.rename(tmp_path / 'old.log')
    log.write_text('新文件\n')
    assert client.get(endpoint).json()['content'] == '新文件\n'
    log.write_text('x' * 300_000)
    result = client.get(endpoint).json()
    assert len(result['content']) <= 256 * 1024
    assert result['truncated'] is True


def test_cross_origin_cannot_initialize_or_login(tmp_path: Path) -> None:
    """登录与初始化同样拒绝跨站写入。

    Args:
        tmp_path: 隔离测试目录。
    """
    client = TestClient(make_app(tmp_path))
    for path in ('setup', 'login', 'register'):
        assert client.post(f'/api/auth/{path}', json=CREDENTIALS,
                           headers={'origin': 'https://evil.example'}).status_code == 403
    assert client.get('/api/auth/status').json()['setup_required'] is True


def test_console_complete_requests_permissions_and_no_truncation(tmp_path: Path) -> None:
    """完整请求独立于日志截断，且仅管理员可读取。

    Args:
        tmp_path: 隔离服务与快照目录。
    """
    from src.tidebound.storage.model_requests import ModelRequestStore, request_run, request_step

    app = make_app(tmp_path)
    admin, user, anonymous = (TestClient(app) for _ in range(3))
    admin.post('/api/auth/setup', json=CREDENTIALS)
    user.post('/api/auth/register', json=CREDENTIALS | {'username': 'ordinary'})
    store = ModelRequestStore(tmp_path / 'agent')
    run_token = request_run.set((uuid4().hex, str(uuid4())))
    step_token = request_step.set(1)
    body = {'model': 'fixture', 'messages': [{'role': 'system', 'content': '完整上下文\n' * 60000}], 'tools': []}
    try:
        snapshot = store.save(body)
    finally:
        request_run.reset(run_token)
        request_step.reset(step_token)
    endpoint = '/api/users/uid-00000001/console/requests'
    assert anonymous.get(endpoint).status_code == 401
    assert user.get(endpoint).status_code == 403
    assert user.get('/api/users/uid-00000002/console/requests').status_code == 403
    assert admin.get('/api/users/uid-00000002/console/requests').status_code == 403
    assert admin.get(endpoint).json()[0]['request_id'] == snapshot.request_id
    assert 'body' not in admin.get(endpoint).json()[0]
    assert admin.get(endpoint + '?offset=50').json() == []
    groups_endpoint = '/api/users/uid-00000001/console/request-runs'
    assert anonymous.get(groups_endpoint).status_code == 401
    assert user.get(groups_endpoint).status_code == 403
    assert admin.get(groups_endpoint).json()[0]['requests'][0]['request_id'] == snapshot.request_id
    assert admin.get(groups_endpoint + '?offset=50').json() == []
    detail = endpoint + '/' + snapshot.request_id
    assert user.get(detail).status_code == 403
    response = admin.get(detail)
    assert response.headers['cache-control'] == 'no-store'
    assert response.json()['body'] == body
    assert admin.get(endpoint + '/' + str(uuid4())).status_code == 404
    assert admin.get(endpoint + '/invalid-path').status_code == 422


def test_only_admin_can_reset_own_context(tmp_path: Path) -> None:
    """管理员重置仅作用于自身，普通账号和跨站请求无权执行。

    Args:
        tmp_path: 隔离测试数据目录。
    """
    app = make_app(tmp_path)
    admin, other, anonymous = (TestClient(app) for _ in range(3))
    admin.post('/api/auth/setup', json=CREDENTIALS)
    other.post('/api/auth/register', json=CREDENTIALS | {'username': 'other'})
    scopes = [app.state.auth.resolve(client.cookies.get('tidebound_session')).scope for client in (admin, other)]
    for scope in scopes:
        app.state.chat.store.save(scope, RunRecord(run_id=str(uuid4()), created_at='2026-09-14T00:00:00Z',
            status='completed', user_content='旧对话', messages=[Message(role='user', content='旧对话'),
            Message(role='assistant', content='旧回复')]))
    endpoint = '/api/chat/context/reset'
    assert anonymous.post(endpoint).status_code == 401
    assert other.post(endpoint).status_code == 403
    assert admin.post(endpoint, headers={'origin': 'https://evil.example'}).status_code == 403
    response = admin.post(endpoint)
    assert response.status_code == 200
    assert response.json()['messages'] == []
    assert response.json()['tool_runs'] == []
    assert response.json()['context_usage']['input_used'] is None
    assert len(other.get('/api/chat/session').json()['messages']) == 2
    assert len(app.state.chat.store.list_runs(scopes[0])) == 1
    assert admin.get('/api/chat/session').json()['messages'] == []


def test_restart_redirects_pages_but_keeps_api_unauthorized(tmp_path: Path) -> None:
    """重启使旧 Cookie 失效；页面回登录，API 保持 HTTP 401。

    Args:
        tmp_path: 隔离账号持久化与应用数据的目录。
    """
    original = TestClient(make_app(tmp_path))
    original.post('/api/auth/setup', json=CREDENTIALS)
    restarted = TestClient(make_app(tmp_path))
    restarted.cookies.update(original.cookies)
    for path in ['/app/uid-00000001', '/app/uid-00000001/console']:
        response = restarted.get(path, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers['location'] == '/app/'
        assert response.headers['cache-control'] == 'no-store'
        assert restarted.get(path).headers['content-type'].startswith('text/html')
    for path in ['/api/auth/me', '/api/chat/session', '/api/users/uid-00000001/console/log']:
        response = restarted.get(path)
        assert response.status_code == 401
        assert response.json() == {'detail': 'Unauthorized'}
        assert response.headers['cache-control'] == 'no-store'
    assert restarted.post('/api/auth/login', json=CREDENTIALS).status_code == 200
    assert restarted.get('/app/uid-00000001').status_code == 200


def test_console_runtime_events_available_without_terminal_debug(tmp_path: Path) -> None:
    """运行事件独立于终端文件，仍受管理员权限保护。"""
    from src.tidebound.runtime.events import emit_event

    app = make_app(tmp_path)
    admin = TestClient(app)
    uid = admin.post('/api/auth/setup', json=CREDENTIALS).json()['uid']
    emit_event(app.state.chat.settings, 'workflow', 'websearch.N02-Retrieve', 'started', run=('owner', 'run'))
    result = admin.get(f'/api/users/{uid}/console/log').json()
    assert 'websearch.N02-Retrieve' in result['events_content']
    assert TestClient(app).get(f'/api/users/{uid}/console/log').status_code == 401
