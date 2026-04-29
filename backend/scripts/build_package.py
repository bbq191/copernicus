#!/usr/bin/env python3
"""backend 部署包打包脚本

用法：
    python backend/scripts/build_package.py [output_dir]

默认输出目录：项目根目录下的 dist/
输出文件名：copernicus-backend-{version}-{YYYYMMDD-HHMM}.tar.gz
"""

import sys
import tarfile
import tomllib
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

# 相对于 backend/ 目录，明确列出要打入包的顶层条目（白名单）
# 增减顶层目录时在此更新，避免无关文件意外入包
INCLUDE_ROOTS = [
    "src",
    "templates",
    "models",
    "scripts",
    "hotwords.txt",
    "pyproject.toml",
    "run.py",
]

# 无论层级深浅，文件/目录名匹配即剔除
EXCLUDE_NAMES: set[str] = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "tests",
    "uploads",
    "examples",
    ".env",
    ".git",
    ".gitignore",
}

# 剔除这些后缀的文件
EXCLUDE_SUFFIXES: set[str] = {".pyc", ".pyo"}

# scripts/ 目录内本脚本自身不打入包（打包工具不属于运行时）
EXCLUDE_SCRIPTS: set[str] = {"build_package.py"}

# ---------------------------------------------------------------------------
# 核心逻辑
# ---------------------------------------------------------------------------

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _should_exclude(path: Path) -> bool:
    """判断 path 是否应被排除。"""
    if path.name in EXCLUDE_NAMES:
        return True
    if path.suffix in EXCLUDE_SUFFIXES:
        return True
    # scripts/ 目录下排除打包脚本本身
    try:
        rel = path.relative_to(BACKEND_DIR / "scripts")
        if rel.parts and rel.parts[0] in EXCLUDE_SCRIPTS:
            return True
    except ValueError:
        pass
    return False


def _iter_files(root: Path):
    """遍历 root 下所有应打包的文件，剔除规则文件后 yield Path。"""
    for path in sorted(root.rglob("*")):
        if any(_should_exclude(p) for p in [path, *path.parents]):
            continue
        if path.is_file():
            yield path


def _read_version(backend_dir: Path) -> str:
    toml_path = backend_dir / "pyproject.toml"
    try:
        with open(toml_path, "rb") as f:
            data = tomllib.load(f)
        return data.get("project", {}).get("version", "0.0.0")
    except Exception:
        return "0.0.0"


def build(output_dir: Path) -> Path:
    version = _read_version(BACKEND_DIR)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M")
    archive_name = f"copernicus-backend-{version}-{timestamp}.tar.gz"
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / archive_name

    included: list[str] = []
    skipped_roots: list[str] = []

    # 检查白名单条目是否存在
    for root_name in INCLUDE_ROOTS:
        entry = BACKEND_DIR / root_name
        if not entry.exists():
            skipped_roots.append(root_name)

    if skipped_roots:
        print(f"[warn] 以下白名单条目在 backend/ 中不存在，已跳过：{skipped_roots}")

    with tarfile.open(archive_path, "w:gz") as tar:
        for root_name in INCLUDE_ROOTS:
            entry = BACKEND_DIR / root_name
            if not entry.exists():
                continue

            if entry.is_file():
                arcname = f"backend/{root_name}"
                tar.add(entry, arcname=arcname)
                included.append(arcname)
            else:
                for file_path in _iter_files(entry):
                    rel = file_path.relative_to(BACKEND_DIR)
                    arcname = f"backend/{rel.as_posix()}"
                    tar.add(file_path, arcname=arcname)
                    included.append(arcname)

    return archive_path, included


def main() -> None:
    output_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else BACKEND_DIR.parent / "dist"

    print(f"打包目录：{BACKEND_DIR}")
    print(f"输出目录：{output_dir}")
    print()

    archive_path, included = build(output_dir)

    print(f"已打包 {len(included)} 个文件：")
    for f in included:
        print(f"  {f}")

    size_kb = archive_path.stat().st_size / 1024
    print()
    print(f"输出文件：{archive_path}")
    print(f"文件大小：{size_kb:.1f} KB")


if __name__ == "__main__":
    main()
