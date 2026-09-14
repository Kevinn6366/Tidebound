"""验证恢复的对话空接口及浏览器隔离的设置、资源保存。"""

from pathlib import Path

from fastapi.testclient import TestClient

from webapp.config import WebSettings
from webapp.main import create_app


def make_client(root: Path) -> TestClient:
    """创建使用测试目录的独立浏览器客户端。

    Args:
        root: 当前测试的界面数据目录。

    Returns:
        带独立 Cookie 容器的客户端。
    """
    return TestClient(create_app(WebSettings(ui_data_dir=root)))


def test_chat_stub_does_not_store_or_generate(tmp_path: Path) -> None:
    """有效输入到达空接口，凭据和旧模型历史不进入接口。

    Args:
        tmp_path: 隔离的测试目录。
    """
    client = make_client(tmp_path)
    response = client.post('/api/chat/messages', json={'content': '你好', 'attachments': []})
    assert response.status_code == 501
    assert response.json()['detail']['code'] == 'chat_not_connected'
    assert list(tmp_path.iterdir()) == []
    assert client.post('/api/chat/messages', json={'content': ''}).status_code == 422
    assert client.post('/api/chat/messages', json={'content': 'test', 'api_key': 'fake'}).status_code == 422


def test_settings_persist_and_are_isolated(tmp_path: Path) -> None:
    """设置刷新可读，不同 Cookie 或伪造命名空间不能互读。

    Args:
        tmp_path: 各浏览器共享的测试数据根目录。
    """
    first, second = make_client(tmp_path), make_client(tmp_path)
    path = '/api/userdata/preview/core/live2d_settings_v35'
    assert first.put(path, json={'typingSpeed': 60}).status_code == 200
    assert first.get(path).json() == {'typingSpeed': 60}
    assert second.get(path).json() is None
    assert first.get('/api/userdata/other/core/live2d_settings_v35').status_code == 403
    batch = first.get('/api/userdata/preview/batch?keys=live2d_settings_v35&media=true').json()
    assert batch['live2d_settings_v35']['typingSpeed'] == 60
    assert batch['_bgm'] == []
    assert 'HttpOnly' in make_client(tmp_path).get('/api/health').headers['set-cookie']


def test_media_upload_and_delete(tmp_path: Path) -> None:
    """原背景上传、列表、文件读取和删除接口可以往返。

    Args:
        tmp_path: 模拟浏览器的资源目录。
    """
    client = make_client(tmp_path)
    path = '/api/userdata/preview/bg_images'
    response = client.post(path, data={'id': 'background', 'name': '背景.png'},
                           files={'file': ('背景.png', b'image-fixture', 'image/png')})
    assert response.status_code == 200
    assert client.get(path).json()[0]['name'] == '背景.png'
    assert client.get(path + '/background/file').content == b'image-fixture'
    assert client.delete(path + '/background').status_code == 200
    assert client.get(path).json() == []
    assert client.get(path + '/background/file').status_code == 404


def test_model_upload_preserves_relative_paths(tmp_path: Path) -> None:
    """角色包按原相对路径读取，拒绝上传越界文件。

    Args:
        tmp_path: 模拟角色资源保存目录。
    """
    client = make_client(tmp_path)
    path = '/api/userdata/preview/models'
    response = client.post(path, data={'id': 'atri', 'name': '亚托莉'}, files=[
        ('files', ('model_root/atri.model3.json', b'{}', 'application/json')),
        ('files', ('model_root/texture.png', b'fixture', 'image/png')),
    ])
    assert response.status_code == 200
    assert client.get(path + '/atri').json()['files'] == ['model_root/atri.model3.json', 'model_root/texture.png']
    assert client.get(path + '/atri/files/model_root/texture.png').content == b'fixture'
    response = client.post(path, data={'id': 'bad', 'name': 'bad'}, files=[
        ('files', ('../escape.txt', b'forbidden', 'text/plain')),
    ])
    assert response.status_code == 400
    assert not list(tmp_path.rglob('escape.txt'))


def test_cross_origin_write_is_rejected_but_vite_is_allowed(tmp_path: Path) -> None:
    """开发代理来源可写，其他站点不能跨来源修改设置。

    Args:
        tmp_path: 测试数据目录。
    """
    client = make_client(tmp_path)
    path = '/api/userdata/preview/core/settings'
    assert client.put(path, json={}, headers={'origin': 'https://example.com'}).status_code == 403
    assert client.put(path, json={}, headers={'origin': 'http://127.0.0.1:5173'}).status_code == 200


def test_login_appearance_and_plugins_remain_editable(tmp_path: Path) -> None:
    """登录外观和立绘插件配置可保存，未实现的账号接口仍不开放。

    Args:
        tmp_path: 浏览器配置保存目录。
    """
    client = make_client(tmp_path)
    assert client.put('/api/login-config', json={'loginPageTitle': '测试标题'}).status_code == 200
    assert client.get('/api/login-config').json()['loginPageTitle'] == '测试标题'
    path = '/api/userdata/preview/plugins/sprite_sets/example'
    assert client.put(path, json={'name': '立绘'}).status_code == 200
    assert client.get(path).json() == {'name': '立绘'}
    assert client.get('/api/userdata/preview/plugins/sprite_sets').json() == [{'key': 'example', 'value': {'name': '立绘'}}]
    upload = client.post(path + '/blob', files={'file': ('sprite.png', b'sprite', 'image/png')})
    assert upload.status_code == 200
    assert client.get(upload.json()['url']).content == b'sprite'
    assert client.post('/api/auth/login', json={}).status_code == 501
