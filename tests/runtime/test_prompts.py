"""验证可整体替换的提示词目录与严格 manifest。"""
import shutil
from pathlib import Path

import pytest

from src.tidebound.config import ROOT
from src.tidebound.errors import AgentError
from src.tidebound.prompting import load_character_bundle


def test_replaced_directory_changes_content(tmp_path: Path) -> None:
    shutil.copytree(ROOT / "prompts", tmp_path / "prompts")
    root = tmp_path / "prompts"
    original = load_character_bundle(root)
    assert "{{" not in original.content
    original.files[0].write_text("替换后的角色内容", encoding="utf-8")
    assert load_character_bundle(root).content == "替换后的角色内容"


@pytest.mark.parametrize("change", ["duplicate", "purpose", "escape", "template", "missing", "empty"])
def test_invalid_bundle(tmp_path: Path, change: str) -> None:
    shutil.copytree(ROOT / "prompts", tmp_path / "prompts")
    root = tmp_path / "prompts"
    manifest = root / "master.yaml"
    content_file = load_character_bundle(root).files[0]
    if change == "duplicate":
        manifest.write_text(manifest.read_text() + "\nprompts: {}\n")
    elif change == "purpose":
        manifest.write_text(manifest.read_text().replace("chat.character:", "chat.other:"))
    elif change == "escape":
        (tmp_path / "secret.md").write_text("private")
        manifest.write_text(manifest.read_text().replace("@master/chat.character/chat.character-zh.md", "@../secret.md"))
    elif change == "template":
        content_file.write_text("{{ .Unknown }}")
    elif change == "missing":
        content_file.unlink()
    elif change == "empty":
        content_file.write_text("")
    with pytest.raises(AgentError) as failure:
        load_character_bundle(root)
    assert failure.value.code == "invalid_prompt_bundle"


def test_tool_injection_is_separate_and_deduplicated(tmp_path: Path) -> None:
    from src.tidebound.prompting import load_tool_injections

    shutil.copytree(ROOT / "prompts", tmp_path / "prompts")
    root = tmp_path / "prompts"
    purpose = "tools.injection.timetools"
    assert "先获取当前时间再回答" not in load_character_bundle(root).content
    content = load_tool_injections(root, (purpose, purpose))
    assert content.count("先获取当前时间再回答") == 1
    assert "{{" not in content
    (root / "master/tools.injection/tools.injection.timetools.md").unlink()
    assert load_character_bundle(root).content
    with pytest.raises(AgentError):
        load_tool_injections(root, (purpose,))
