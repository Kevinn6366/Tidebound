"""只读共享展示资源目录，不访问用户数据或模型服务。"""

from pathlib import Path
from urllib.parse import quote

from webapp.schemas import ModelAsset


def list_model_assets(directory: Path) -> list[ModelAsset]:
    """沿用 GWC-Pro 的 Live2D 清单格式，生成同源资源路径。

    Args:
        directory: 管理员预置的公共角色资源根目录，不应包含用户私有文件。

    Returns:
        按路径排序的模型清单；目录尚未创建时返回空清单。

    Raises:
        OSError: 当资源目录无法读取时抛出。
    """
    root = directory.resolve()
    if not root.is_dir():
        return []
    models = []
    for path in sorted(root.rglob("*.json")):
        if not path.name.endswith((".model3.json", ".model.json")):
            continue
        # 目录外符号链接既不出现在清单，也不允许由静态资源接口读取。
        if not path.is_file() or not path.resolve().is_relative_to(root):
            continue
        relative_path = path.relative_to(root).as_posix()
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        models.append(ModelAsset(name=path.parent.name, path=f"/models/{quote(relative_path, safe='/')}"))
    return models


def resolve_public_file(directory: Path, relative_path: str) -> Path | None:
    """解析公开目录内的文件，拒绝目录穿越、隐藏文件及越界链接。

    Args:
        directory: 唯一允许公开读取的资源根目录。
        relative_path: URL 解码后的资源相对路径。

    Returns:
        可以读取的真实文件路径；不存在或越界时返回 None。

    Raises:
        OSError: 当底层文件系统无法解析路径时抛出。
    """
    if "\\" in relative_path or "\x00" in relative_path:
        return None
    relative = Path(relative_path)
    if relative.is_absolute() or any(part.startswith(".") for part in relative.parts):
        return None
    root = directory.resolve()
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root) or not candidate.is_file():
        return None
    return candidate
