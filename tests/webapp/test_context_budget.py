"""验证预算配置的鉴权、持久化与会话展示。"""
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from src.tidebound.context.budget import context_usage
from src.tidebound.runtime.types import Message, RunRecord
from tests.webapp.test_auth_console import CREDENTIALS, make_app


def test_budget_permissions_validation_and_persistence(tmp_path: Path) -> None:
    """预算覆盖仅属于管理员自身，非法请求不改变原值。

    Args:
        tmp_path: 隔离账号与运行数据的临时目录。
    """
    app = make_app(tmp_path)
    admin, user, anonymous = (TestClient(app) for _ in range(3))
    path = '/api/chat/context/budget'
    assert anonymous.get(path).status_code == 401
    assert anonymous.put(path, json={'context_limit': 65536}).status_code == 401
    admin.post('/api/auth/setup', json=CREDENTIALS)
    user.post('/api/auth/register', json=CREDENTIALS | {'username': 'ordinary'})
    assert user.get(path).status_code == 403
    assert user.put(path, json={'context_limit': 65536}).status_code == 403
    original = admin.get(path).json()
    for invalid in [True, '65536', 65536.5, 2047, original['output_reserved'] + original['format_margin']]:
        assert admin.put(path, json={'context_limit': invalid}).status_code == 422
    assert admin.put(path, json={'context_limit': 65536, 'owner': str(uuid4())}).status_code == 422
    assert admin.get(path).json() == original
    scope = app.state.auth.resolve(admin.cookies.get('tidebound_session')).scope
    app.state.chat.store.save(scope, RunRecord(
        run_id=str(uuid4()), created_at='2026-09-16T00:00:00Z', status='completed', user_content='你好',
        messages=[Message(role='assistant', content='你好')], context_usage=context_usage(app.state.chat.settings, 5000)))
    assert admin.put(path, json={'context_limit': 65536}).json()['total'] == 65536
    session = admin.get('/api/chat/session').json()
    assert session['context_usage']['total'] == 65536
    assert session['context_usage']['input_used'] is None
    assert len(session['messages']) == 2
    assert user.get('/api/chat/session').json()['context_usage']['total'] == original['total']
    assert admin.post('/api/chat/context/reset').status_code == 200
    assert admin.get(path).json()['total'] == 65536
    restarted = TestClient(make_app(tmp_path))
    restarted.post('/api/auth/login', json=CREDENTIALS)
    assert restarted.get(path).json()['total'] == 65536
    app.state.chat.settings.mode = 'prod'
    assert admin.put(path, json={'context_limit': 131072}).status_code == 403
