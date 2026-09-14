"""通信层路径配置；默认值不依赖启动时的工作目录。"""

from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class WebSettings:
    """前端构建产物与管理员预置的共享角色资源位置。"""

    frontend_dist: Path = PROJECT_ROOT / "webfrontend" / "dist"
    models_dir: Path = PROJECT_ROOT / "data" / "assets" / "live2d_models"
    ui_data_dir: Path = PROJECT_ROOT / "data" / "ui-preview"
    debug_log_path: Path = PROJECT_ROOT / "data" / "agent-debug.log"
    dev_frontend_origin: str = "http://127.0.0.1:5173"
