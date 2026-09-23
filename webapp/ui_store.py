"""迁移预览的界面设置与资源存储，不作为长期对话的事实来源。"""

import json
import shutil
from pathlib import Path
from uuid import uuid4

from pydantic import JsonValue


class UiStore:
    """每个浏览器独立的开发预览目录，不读取上游用户数据。"""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def path(self, relative: str) -> Path:
        """解析本浏览器预览目录内的资源路径。

        Args:
            relative: 预览文件的相对路径。

        Returns:
            验证在根目录内的绝对路径。

        Raises:
            ValueError: 路径为空、包含隐藏段、反斜杠或越界时抛出。
        """
        parts = Path(relative)
        if not relative or '\\' in relative or '\x00' in relative or parts.is_absolute():
            raise ValueError("资源路径非法")
        if any(part.startswith('.') for part in parts.parts):
            raise ValueError("资源路径非法")
        target = (self.root / parts).resolve()
        if not target.is_relative_to(self.root):
            raise ValueError("资源路径越界")
        return target

    def read_json(self, relative: str) -> JsonValue:
        """读取界面配置，缺失文件不冒充读取失败。

        Args:
            relative: JSON 文件相对路径。

        Returns:
            文件内容；不存在时返回 None。

        Raises:
            ValueError: 路径非法或 JSON 损坏。
            OSError: 文件无法读取。
        """
        target = self.path(relative)
        return json.loads(target.read_text(encoding='utf-8')) if target.is_file() else None

    def write_bytes(self, relative: str, content: bytes) -> None:
        """原子替换预览文件，避免刷新时读到半份设置。

        Args:
            relative: 写入的文件相对路径。
            content: 完整文件内容。

        Raises:
            ValueError: 路径不合法。
            OSError: 文件写入失败。
        """
        target = self.path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f'{target.name}.{uuid4().hex}.tmp')
        try:
            temporary.write_bytes(content)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)

    def write_json(self, relative: str, value: JsonValue) -> None:
        """将界面数据编码为 JSON 并原子写入。

        Args:
            relative: JSON 文件相对路径。
            value: 可序列化的界面数据。

        Raises:
            ValueError: 路径或数据非法。
            OSError: 文件写入失败。
        """
        self.write_bytes(relative, json.dumps(value, ensure_ascii=False).encode('utf-8'))

    def list_json(self, relative: str) -> list[JsonValue]:
        """读取指定集合内的 JSON 条目。

        Args:
            relative: 界面数据集合的相对目录。

        Returns:
            按文件名排序的条目列表。

        Raises:
            ValueError: 路径或 JSON 数据非法。
            OSError: 目录无法读取。
        """
        directory = self.path(relative)
        return [self.read_json(str(path.relative_to(self.root))) for path in sorted(directory.glob('*.json'))]

    def delete(self, relative: str) -> None:
        """删除本浏览器预览目录内的单个文件或资源集合。

        Args:
            relative: 需要删除的资源相对路径。

        Raises:
            ValueError: 删除目标越界。
            OSError: 删除失败。
        """
        target = self.path(relative)
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink(missing_ok=True)
