"""使用实际 bundle 加载器校验指定 Markdown 内容文件。"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.tidebound.errors import AgentError
from src.tidebound.prompting import load_character_bundle


def main() -> int:
    """验证 manifest 和文件引用，返回可供 CI 使用的退出码。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("file", type=Path)
    args = parser.parse_args()
    try:
        bundle = load_character_bundle(ROOT / "prompts")
        if args.file.resolve() not in bundle.files:
            print(f"ERROR: {args.file.resolve()}: file is not referenced by master.yaml")
            return 2
    except AgentError as error:
        print(f"ERROR: {args.file.resolve()}: {error.code}")
        return 1
    print(f"OK: {args.file.resolve()} ({bundle.name})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
