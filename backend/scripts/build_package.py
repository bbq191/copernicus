#!/usr/bin/env python3
"""backend 部署包打包脚本

用法：
    python backend/scripts/build_package.py [output_dir] [--no-models]

默认输出目录：项目根目录下的 dist/
输出文件名：copernicus-backend-{version}-{YYYYMMDD-HHMM}.tar.gz
--no-models：不打入 models/（模型体积可达数 GB，可单独传输）
"""

import argparse
import tarfile
import tomllib
from datetime import datetime
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent

# 相对于 backend/ 的顶层白名单：增减入包内容只改这里，避免无关文件意外入包
INCLUDE_ROOTS = [
    "src",
    "templates",
    "models",
    "scripts",
    "hotwords.txt",
    "pyproject.toml",
    ".env.prod",
    ".env.example",
]

# 目录或文件名（相对 backend/ 的任一层级）命中即剔除
EXCLUDE_NAMES = frozenset({
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "tests", "uploads", "examples", ".env", ".git", ".gitignore",
})
EXCLUDE_SUFFIXES = frozenset({".pyc", ".pyo"})
# 打包工具本身不属于运行时
EXCLUDE_FILES = frozenset({Path("scripts/build_package.py")})


def _is_excluded(rel: Path) -> bool:
    """rel 为相对 backend/ 的路径。只检查相对部分，避免上层目录恰好叫 tests/examples 时全部被剔除。"""
    return (
        rel in EXCLUDE_FILES
        or rel.suffix in EXCLUDE_SUFFIXES
        or any(part in EXCLUDE_NAMES for part in rel.parts)
    )


def _iter_files(roots: list[str]):
    for name in roots:
        entry = BACKEND_DIR / name
        if not entry.exists():
            print(f"[warn] 白名单条目不存在，已跳过：{name}")
            continue
        candidates = [entry] if entry.is_file() else sorted(entry.rglob("*"))
        for path in candidates:
            rel = path.relative_to(BACKEND_DIR)
            if path.is_file() and not _is_excluded(rel):
                yield path, rel


def _read_version() -> str:
    try:
        with open(BACKEND_DIR / "pyproject.toml", "rb") as f:
            return tomllib.load(f)["project"]["version"]
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return "0.0.0"


def build(output_dir: Path, include_models: bool = True) -> tuple[Path, list[str]]:
    roots = [r for r in INCLUDE_ROOTS if include_models or r != "models"]
    timestamp = datetime.now().strftime("%Y%m%d-%H%M")
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / f"copernicus-backend-{_read_version()}-{timestamp}.tar.gz"

    included: list[str] = []
    with tarfile.open(archive_path, "w:gz") as tar:
        for path, rel in _iter_files(roots):
            arcname = f"backend/{rel.as_posix()}"
            tar.add(path, arcname=arcname)
            included.append(arcname)
    return archive_path, included


def main() -> None:
    parser = argparse.ArgumentParser(description="打包 backend 部署包")
    parser.add_argument("output_dir", nargs="?", type=Path, default=BACKEND_DIR.parent / "dist")
    parser.add_argument("--no-models", action="store_true", help="不打入 models/ 目录")
    args = parser.parse_args()

    print(f"打包目录：{BACKEND_DIR}\n输出目录：{args.output_dir}\n")
    archive_path, included = build(args.output_dir, include_models=not args.no_models)

    print(f"已打包 {len(included)} 个文件")
    print(f"输出文件：{archive_path}")
    print(f"文件大小：{archive_path.stat().st_size / 1024 / 1024:.1f} MB")


if __name__ == "__main__":
    main()
