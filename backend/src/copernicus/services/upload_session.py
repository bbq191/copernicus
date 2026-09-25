"""分片上传会话管理：以文件 SHA-256 为 key，负责会话创建、断点续传、数据组装。"""

import asyncio
import json
import logging
import re
import shutil
import uuid
from pathlib import Path

from copernicus.exceptions import InvalidIdentifierError

logger = logging.getLogger(__name__)

_SESSIONS_DIR = ".sessions"
_INCOMING_DIR = ".incoming"
_SAFE_FILE_HASH = re.compile(r'^[0-9a-f]{64}$')


class UploadSessionService:
    """管理 upload_dir/.sessions/{file_hash}/ 目录下的分片上传会话。"""

    def __init__(self, upload_dir: Path) -> None:
        self._sessions_dir = upload_dir / _SESSIONS_DIR
        self._sessions_dir.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, asyncio.Lock] = {}

    def lock(self, file_hash: str) -> asyncio.Lock:
        """同一文件的分块处理必须串行：重试或重复请求并发到达时，避免交错写入。"""
        self._session_dir(file_hash)  # 顺带校验哈希格式
        return self._locks.setdefault(file_hash, asyncio.Lock())

    def _session_dir(self, file_hash: str) -> Path:
        if not _SAFE_FILE_HASH.fullmatch(file_hash):
            raise InvalidIdentifierError(f"Invalid file_hash format: {file_hash!r}")
        return self._sessions_dir / file_hash

    def _meta_path(self, file_hash: str) -> Path:
        return self._session_dir(file_hash) / "session.json"

    def _data_path(self, file_hash: str) -> Path:
        return self._session_dir(file_hash) / "data.bin"

    def data_path(self, file_hash: str) -> Path:
        """已接收数据的文件路径；提交任务时直接把它移走，不再读入内存。"""
        return self._data_path(file_hash)

    @staticmethod
    def _write_meta(path: Path, meta: dict) -> None:
        """先写临时文件再改名：事件循环里的查询与线程里的追加会并发读取它，不能读到写了一半的内容。"""
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)

    def get_or_create(
        self,
        file_hash: str,
        filename: str,
        total_size: int,
        hotwords: list[str] | None = None,
        visual_scan: bool = False,
        generate_summary: bool = True,
        template_id: str = "universal",
    ) -> int:
        """查找或创建会话，返回当前已接收字节数（0 = 新会话）。"""
        meta_path = self._meta_path(file_hash)

        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text("utf-8"))
                meta["hotwords"] = hotwords or []
                meta["visual_scan"] = visual_scan
                meta["generate_summary"] = generate_summary
                meta["template_id"] = template_id
                self._write_meta(meta_path, meta)
            except (json.JSONDecodeError, OSError):
                pass
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
            "generate_summary": generate_summary,
            "template_id": template_id,
        }
        self._write_meta(meta_path, meta)
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

        new_offset = current + len(chunk)
        if new_offset > session["total_size"]:
            raise ValueError(
                f"Chunk exceeds declared size: {new_offset} > {session['total_size']}"
            )

        with self._data_path(file_hash).open("ab") as f:
            f.write(chunk)

        complete = new_offset >= session["total_size"]
        logger.info(
            "Session %.8s: %d/%d bytes complete=%s",
            file_hash, new_offset, session["total_size"], complete,
        )
        return new_offset, complete

    def truncate(self, file_hash: str, size: int) -> None:
        """回退到指定大小：末块提交失败（如队列已满）时撤销刚追加的块，客户端可原样重传。"""
        with self._data_path(file_hash).open("r+b") as f:
            f.truncate(size)

    def delete_session(self, file_hash: str) -> None:
        d = self._session_dir(file_hash)
        if d.exists():
            shutil.rmtree(d)
            logger.info("Deleted session %.8s", file_hash)
        self._locks.pop(file_hash, None)


def incoming_path(upload_dir: Path) -> Path:
    """为一次表单上传分配落盘路径。与任务目录同处 upload_dir，后续移入任务目录只是一次 rename。"""
    incoming = upload_dir / _INCOMING_DIR
    incoming.mkdir(parents=True, exist_ok=True)
    return incoming / f"{uuid.uuid4().hex}.part"
