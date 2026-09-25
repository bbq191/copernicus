"""文件哈希：分块读取，避免把大文件整体读入内存。"""

import hashlib
from pathlib import Path

_BLOCK = 4 * 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(_BLOCK):
            digest.update(block)
    return digest.hexdigest()
