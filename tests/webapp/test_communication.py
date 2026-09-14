"""验证展示通信、静态资源边界与未迁移业务的明确失败。"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.tidebound.config import AgentSettings
from tests.support.account_store import FileUserStore
from webapp.config import WebSettings
from webapp.main import create_app


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """在隔离目录中创建展示通信测试客户端。

    Args:
        tmp_path: pytest 为当前测试分配的临时目录。

    Returns:
        指向临时前端与模型目录的客户端。
    """
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>Tidebound</html>", encoding="utf-8")
    (dist / "main.js").write_text("export {};", encoding="utf-8")
    models = tmp_path / "models" / "亚托莉 示例"
    models.mkdir(parents=True)
    (models / "atri.model3.json").write_text('{"Version": 3}', encoding="utf-8")
    return TestClient(create_app(WebSettings(frontend_dist=dist, models_dir=models.parent, ui_data_dir=tmp_path / 'ui'), AgentSettings(data_dir=tmp_path / 'agent'), user_store=FileUserStore(tmp_path / 'auth' / 'users.json')))


def test_bootstrap_contract(client: TestClient) -> None:
    """能力声明只报告已实现的展示功能。

    Args:
        client: 当前隔离测试客户端。
    """
    assert client.get("/api/health").json() == {"status": "ok", "service": "tidebound-webapp"}
    assert client.get("/api/capabilities").json() == {
        "mode": "agent-dev", "character": "atri", "tools": ["get_current_time"], "chat_interface": True, "settings": True,
        "chat": False, "authentication": True, "history": True, "live2d": True,
    }
    assert client.post("/api/auth/setup", json={"username": "admin", "password": "test-password"}).status_code == 201
    assert client.get("/api/login-config").json()["loginPageTitle"] == "汐伴 · Tidebound"


def test_model_paths_are_same_origin_and_url_encoded(client: TestClient) -> None:
    """中文及空格资源名称必须可以直接由浏览器读取。

    Args:
        client: 当前隔离测试客户端。
    """
    model = client.get("/api/models").json()["models"][0]
    assert model["name"] == "亚托莉 示例"
    assert model["path"].startswith("/models/")
    assert "%20" in model["path"]
    response = client.get(model["path"])
    assert response.status_code == 200
    assert response.json() == {"Version": 3}


def test_frontend_redirect_and_missing_assets(client: TestClient) -> None:
    """入口重定向可用，缺失 JavaScript 不能返回 HTML 成功响应。

    Args:
        client: 当前隔离测试客户端。
    """
    for path in ("/", "/app"):
        assert client.get(path, follow_redirects=False).headers["location"] == "/app/"
    assert client.get("/app/").headers["content-type"].startswith("text/html")
    assert "javascript" in client.get("/app/main.js").headers["content-type"]
    assert client.get("/app/missing.js").status_code == 404


@pytest.mark.parametrize("prefix", ["/app/", "/models/"])
@pytest.mark.parametrize("path", ["%2e%2e/secret.txt", "%2fetc/passwd", "..%5csecret.txt", ".env"])
def test_reject_path_escape(client: TestClient, prefix: str, path: str) -> None:
    """公开文件接口拒绝目录穿越及隐藏凭据。

    Args:
        client: 当前隔离测试客户端。
        prefix: 待测试的公开文件路由。
        path: 编码后的越界或隐藏文件路径。
    """
    assert client.get(prefix + path).status_code == 404


def test_symlink_outside_public_directory_is_not_exposed(tmp_path: Path) -> None:
    """资源目录里的外部链接既不列出，也不能读取。

    Args:
        tmp_path: 存放模拟私有文件与公开目录的临时目录。
    """
    secret = tmp_path / "secret.model3.json"
    secret.write_text("private", encoding="utf-8")
    public = tmp_path / "public"
    public.mkdir()
    (public / "outside.model3.json").symlink_to(secret)
    client = TestClient(create_app(WebSettings(frontend_dist=public, models_dir=public)))
    assert client.get("/api/models").json() == {"models": []}
    assert client.get("/models/outside.model3.json").status_code == 404
    assert client.get("/app/outside.model3.json").status_code == 404


def test_missing_directories_do_not_break_api_or_create_data(tmp_path: Path) -> None:
    """首次启动无需旧运行数据，未构建页面给出准确的 503。

    Args:
        tmp_path: 当前测试的空目录。
    """
    settings = WebSettings(frontend_dist=tmp_path / "dist", models_dir=tmp_path / "models")
    client = TestClient(create_app(settings))
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/models").json() == {"models": []}
    assert client.get("/app/").status_code == 503
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("method,path", [
    ("POST", "/v1/chat/completions"), ("GET", "/v1/models"),
    ("POST", "/api/opencode/run"),
    ("GET", "/api/bridge/pull"),
    ("GET", "/admin"), ("GET", "/admin/api/skills"),
])
def test_old_business_is_never_forwarded(client: TestClient, method: str, path: str) -> None:
    """旧业务请求必须明确失败，不能伪造保存或执行成功。

    Args:
        client: 隔离的展示通信客户端。
        method: 原上游接口的 HTTP 方法。
        path: 原上游业务接口路径。
    """
    assert client.post("/api/auth/setup", json={"username": "admin", "password": "test-password"}).status_code == 201
    response = client.request(method, path)
    assert response.status_code == 501
    assert response.json()["detail"]["code"] == "not_migrated"
