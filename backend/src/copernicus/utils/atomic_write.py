"""原子文件写入：先写临时文件再 rename，避免进程崩溃/并发读导致读到部分写入的内容。"""

import tempfile
from pathlib import Path


def atomic_write(dest: Path, content: str) -> None:
    """将 content 写入 dest；写入失败时清理临时文件，不改动原文件。"""
    tmp_fd, tmp_path = tempfile.mkstemp(dir=str(dest.parent), suffix=".tmp")
    try:
        with open(tmp_fd, "w", encoding="utf-8") as f:
            f.write(content)
        Path(tmp_path).replace(dest)
    except BaseException:
        Path(tmp_path).unlink(missing_ok=True)
        raise
