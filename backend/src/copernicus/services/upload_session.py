"""分片上传会话管理：以文件 SHA-256 为 key，负责会话创建、断点续传、数据组装。"""

import json
import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

_SESSIONS_DIR = ".sessions"


class UploadSessionService:
    """管理 upload_dir/.sessions/{file_hash}/ 目录下的分片上传会话。"""

    def __init__(self, upload_dir: Path) -> None:
        self._sessions_dir = upload_dir / _SESSIONS_DIR
        self._sessions_dir.mkdir(parents=True, exist_ok=True)

    def _session_dir(self, file_hash: str) -> Path:
        return self._sessions_dir / file_hash

    def _meta_path(self, file_hash: str) -> Path:
        return self._session_dir(file_hash) / "session.json"

    def _data_path(self, file_hash: str) -> Path:
        return self._session_dir(file_hash) / "data.bin"

    def get_or_create(
        self,
        file_hash: str,
        filename: str,
        total_size: int,
        hotwords: list[str] | None = None,
        visual_scan: bool = False,
    ) -> int:
        """查找或创建会话，返回当前已接收字节数（0 = 新会话）。"""
        meta_path = self._meta_path(file_hash)

        if meta_path.exists():
            data = self._data_path(file_hash)
            offset = data.stat().st_size if data.exists() else 0
            logger.info("Resuming session %.8s at offset %d", file_hash, offset)
            return offset

        sd = self._session_dir(file_hash)
        sd.mkdir(parents=True, exist_ok=True)
        meta = {
            "hash": file_hash,
            "filename": filename,
            "total_size": total_size,
            "hotwords": hotwords or [],
            "visual_scan": visual_scan,
        }
        meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        logger.info("New session %.8s total=%d bytes", file_hash, total_size)
        return 0

    def get_session(self, file_hash: str) -> dict | None:
        """返回会话元数据（含 received_bytes）；不存在时返回 None。"""
        meta_path = self._meta_path(file_hash)
        if not meta_path.exists():
            return None
        try:
            meta = json.loads(meta_path.read_text("utf-8"))
            data = self._data_path(file_hash)
            meta["received_bytes"] = data.stat().st_size if data.exists() else 0
            return meta
        except (json.JSONDecodeError, OSError):
            return None

    def append_chunk(self, file_hash: str, offset: int, chunk: bytes) -> tuple[int, bool]:
        """追加数据块。返回 (new_offset, complete)。offset 不匹配时抛 ValueError。"""
        session = self.get_session(file_hash)
        if session is None:
            raise ValueError(f"Session {file_hash[:8]}... not found")

        current = session["received_bytes"]
        if offset != current:
            raise ValueError(f"Offset mismatch: expected {current}, got {offset}")

        with self._data_path(file_hash).open("ab") as f:
            f.write(chunk)

        new_offset = current + len(chunk)
        complete = new_offset >= session["total_size"]
        logger.info(
            "Session %.8s: %d/%d bytes complete=%s",
            file_hash, new_offset, session["total_size"], complete,
        )
        return new_offset, complete

    def read_assembled(self, file_hash: str) -> bytes:
        return self._data_path(file_hash).read_bytes()

    def delete_session(self, file_hash: str) -> None:
        d = self._session_dir(file_hash)
        if d.exists():
            shutil.rmtree(d)
            logger.info("Deleted session %.8s", file_hash)
