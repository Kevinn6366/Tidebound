"""验证开发情感增强设置的权限、严格输入、账号隔离与持久化。"""

import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from src.tidebound.runtime.types import Message, RunRecord
from src.tidebound.storage.emotion_enhancement import EmotionEnhancementStore, EmotionSetting
from tests.webapp.test_auth_console import CREDENTIALS, make_app

ENDPOINT = "/api/chat/emotion-enhancement"
FIXTURE_KEY = "fixture-emotion-key-never-returned"
FIXTURE_MODEL = "fixture-emotion-instruct"


def configured_app(root: Path) -> FastAPI:
    """使用测试凭据组装应用，不读取真实模型配置或访问供应商。

    Args:
        root: 隔离账号和运行数据的 pytest 临时目录。

    Returns:
        情感增强配置齐备的测试应用。
    """
    app = make_app(root)
    app.state.chat.settings.emotion_base_url = "https://emotion.example/v1"
    app.state.chat.settings.emotion_api_key = SecretStr(FIXTURE_KEY)
    app.state.chat.settings.emotion_model = FIXTURE_MODEL
    return app


def test_emotion_permissions_validation_and_secret_boundary(tmp_path: Path) -> None:
    """仅管理员可读取与切换；输入不能注入账号、凭据或非布尔值。

    Args:
        tmp_path: 隔离账号与运行设置的临时目录。
    """
    app = configured_app(tmp_path)
    admin, user, anonymous = (TestClient(app) for _ in range(3))
    assert anonymous.get(ENDPOINT).status_code == 401
    assert anonymous.put(ENDPOINT, json={"enabled": True}).status_code == 401
    assert admin.post("/api/auth/setup", json=CREDENTIALS).status_code == 201
    assert user.post("/api/auth/register", json=CREDENTIALS | {"username": "ordinary"}).status_code == 201
    assert user.get(ENDPOINT).status_code == 403
    assert user.put(ENDPOINT, json={"enabled": True}).status_code == 403
    original = admin.get(ENDPOINT)
    assert original.status_code == 200
    assert original.json() == {"enabled": False, "configured": True, "model": FIXTURE_MODEL}
    assert FIXTURE_KEY not in original.text
    for invalid in ["true", "false", 1, 0, None, [], {}]:
        assert admin.put(ENDPOINT, json={"enabled": invalid}).status_code == 422
    assert admin.put(ENDPOINT, json={}).status_code == 422
    for extra in [{"owner": str(uuid4())}, {"api_key": "injected"}, {"model": "injected"}]:
        assert admin.put(ENDPOINT, json={"enabled": True, **extra}).status_code == 422
    assert admin.put(ENDPOINT, json={"enabled": True},
                     headers={"origin": "https://foreign.example"}).status_code == 403
    assert admin.get(ENDPOINT).json() == original.json()
    selected = admin.put(ENDPOINT, json={"enabled": True})
    assert selected.status_code == 200
    assert selected.json() == {"enabled": True, "configured": True, "model": FIXTURE_MODEL}
    assert FIXTURE_KEY not in selected.text


def test_emotion_scope_reset_and_restart_persistence(tmp_path: Path) -> None:
    """开关只属于登录管理员，刷新、清空上下文与重启均保留选择。

    Args:
        tmp_path: 隔离账号、执行记录与设置的临时目录。
    """
    app = configured_app(tmp_path)
    admin, other, same = (TestClient(app) for _ in range(3))
    admin.post("/api/auth/setup", json=CREDENTIALS)
    other.post("/api/auth/register", json=CREDENTIALS | {"username": "ordinary"})
    same.post("/api/auth/login", json=CREDENTIALS)
    owner = app.state.auth.resolve(admin.cookies.get("tidebound_session")).scope
    other_owner = app.state.auth.resolve(other.cookies.get("tidebound_session")).scope
    store = EmotionEnhancementStore(tmp_path / "agent")
    assert admin.put(ENDPOINT, json={"enabled": True}).status_code == 200
    assert same.get(ENDPOINT).json()["enabled"] is True
    assert store.load(other_owner).enabled is False
    saved = tmp_path / "agent" / UUID(owner).hex / "state" / "emotion-enhancement.json"
    assert json.loads(saved.read_text(encoding="utf-8")) == {"enabled": True}
    app.state.chat.store.save(owner, RunRecord(
        run_id=str(uuid4()), created_at="2026-09-20T00:00:00Z", status="completed",
        user_content="旧对话", messages=[Message(role="assistant", content="旧回复")],
    ))
    assert admin.post("/api/chat/context/reset").status_code == 200
    assert admin.get(ENDPOINT).json()["enabled"] is True
    assert admin.get("/api/chat/session").json()["messages"] == []
    restarted = TestClient(configured_app(tmp_path))
    assert restarted.post("/api/auth/login", json=CREDENTIALS).status_code == 200
    assert restarted.get(ENDPOINT).json()["enabled"] is True
    assert restarted.put(ENDPOINT, json={"enabled": False}).json()["enabled"] is False
    assert store.load(owner).enabled is False
    assert store.load(other_owner).enabled is False


def test_emotion_missing_configuration_and_production_mode(tmp_path: Path) -> None:
    """配置丢失后仍可关闭，但不能启用；生产模式不开放开发接口。

    Args:
        tmp_path: 隔离账号与运行设置的临时目录。
    """
    app = configured_app(tmp_path)
    admin = TestClient(app)
    admin.post("/api/auth/setup", json=CREDENTIALS)
    assert admin.put(ENDPOINT, json={"enabled": True}).status_code == 200
    app.state.chat.settings.emotion_api_key = SecretStr("")
    assert admin.get(ENDPOINT).json()["configured"] is False
    disabled = admin.put(ENDPOINT, json={"enabled": False})
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False
    unavailable = admin.put(ENDPOINT, json={"enabled": True})
    assert unavailable.status_code == 409
    assert unavailable.json()["detail"]["code"] == "emotion_not_configured"
    assert admin.get(ENDPOINT).json()["enabled"] is False
    app.state.chat.settings.mode = "prod"
    assert admin.get(ENDPOINT).status_code == 403
    assert admin.put(ENDPOINT, json={"enabled": True}).status_code == 403
    assert admin.put(ENDPOINT, json={"enabled": False}).status_code == 403


def test_emotion_store_rejects_corruption_and_preserves_failed_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """存储不吞掉损坏和写入错误，替换失败不会覆盖旧设置或泄漏临时文件。

    Args:
        tmp_path: 隔离设置文件的临时目录。
        monkeypatch: 用受控失败替代文件原子替换的测试夹具。
    """
    owner = str(uuid4())
    store = EmotionEnhancementStore(tmp_path)
    assert store.load(owner).enabled is False
    store.save(owner, EmotionSetting(enabled=True))

    def fail_replace(source: Path, target: Path) -> None:
        """模拟落盘失败，验证原子替换边界。

        Args:
            source: 已写完的临时设置文件。
            target: 应被原子替换的正式设置文件。

        Raises:
            OSError: 始终模拟磁盘写入失败。
        """
        raise OSError("fixture storage failure")

    with monkeypatch.context() as patch:
        patch.setattr("src.tidebound.storage.emotion_enhancement.os.replace", fail_replace)
        with pytest.raises(OSError, match="fixture storage failure"):
            store.save(owner, EmotionSetting(enabled=False))
    assert store.load(owner).enabled is True
    directory = tmp_path / UUID(owner).hex / "state"
    assert not list(directory.glob(".*.tmp"))
    for corrupt in ['{"enabled":"true"}', '{"enabled":true,"api_key":"injected"}', '{']:
        (directory / "emotion-enhancement.json").write_text(corrupt, encoding="utf-8")
        with pytest.raises(ValueError):
            store.load(owner)
    with pytest.raises(ValueError):
        store.load("../another-account")
