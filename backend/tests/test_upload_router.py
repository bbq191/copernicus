import hashlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import MagicMock

from copernicus.config import Settings
from copernicus.error_handlers import register_error_handlers
from copernicus.routers.upload import router as upload_router
from copernicus.services.persistence import PersistenceService
from copernicus.services.task_store import TaskStore
from copernicus.services.upload_session import UploadSessionService

DATA = b"0123456789" * 10  # 100 字节
FILE_HASH = hashlib.sha256(DATA).hexdigest()


@pytest.fixture
def env(tmp_path):
    persistence = PersistenceService(tmp_path)
    store = TaskStore(MagicMock(), persistence, Settings(upload_dir=tmp_path))
    # 不真正运行流水线，只关心上传与落盘
    store._spawn = lambda task_id, coro: coro.close()
    sessions = UploadSessionService(tmp_path)

    app = FastAPI()
    app.state.task_store = store
    app.state.upload_session = sessions
    app.include_router(upload_router)
    register_error_handlers(app)
    return TestClient(app), store, sessions, persistence


def _open(client, total=len(DATA), file_hash=FILE_HASH, name="meeting.wav"):
    return client.get(
        f"/api/v1/uploads/{file_hash}", params={"filename": name, "total_size": total}
    )


def _put(client, start, chunk, total=len(DATA), file_hash=FILE_HASH):
    end = start + len(chunk) - 1
    return client.patch(
        f"/api/v1/uploads/{file_hash}",
        content=chunk,
        headers={"Content-Range": f"bytes {start}-{end}/{total}"},
    )


class TestChunkedUpload:
    def test_full_upload_creates_task_and_persists_media(self, env):
        client, store, sessions, persistence = env
        assert _open(client).json()["offset"] == 0

        r1 = _put(client, 0, DATA[:60])
        assert r1.json() == {"received": 60, "complete": False, "task_id": None}
        r2 = _put(client, 60, DATA[60:])
        body = r2.json()

        assert body["complete"] is True and body["task_id"]
        task_id = body["task_id"]
        assert persistence.find_audio(task_id).read_bytes() == DATA
        assert persistence.load_meta(task_id)["hash"] == FILE_HASH
        assert store.get(task_id).audio_path
        assert sessions.get_session(FILE_HASH) is None  # 会话已清理

    def test_video_extension_stored_as_video(self, env):
        client, _, _, persistence = env
        _open(client, name="clip.mp4")
        task_id = _put(client, 0, DATA).json()["task_id"]
        assert persistence.find_video(task_id) is not None

    def test_resume_returns_received_offset(self, env):
        client, *_ = env
        _open(client)
        _put(client, 0, DATA[:40])
        assert _open(client).json()["offset"] == 40

    def test_wrong_offset_is_409(self, env):
        client, *_ = env
        _open(client)
        _put(client, 0, DATA[:40])
        assert _put(client, 10, DATA[10:50]).status_code == 409

    def test_chunk_beyond_declared_size_is_rejected(self, env):
        client, _, sessions, _ = env
        _open(client)
        r = _put(client, 0, DATA + b"extra")
        assert r.status_code == 409
        assert "exceeds" in r.json()["detail"]
        assert sessions.get_session(FILE_HASH)["received_bytes"] == 0

    def test_hash_mismatch_is_422_and_session_dropped(self, env):
        client, _, sessions, _ = env
        bad = b"x" * len(DATA)
        _open(client)
        r = _put(client, 0, bad)
        assert r.status_code == 422
        assert sessions.get_session(FILE_HASH) is None

    def test_unknown_session_is_404(self, env):
        client, *_ = env
        assert _put(client, 0, DATA).status_code == 404

    def test_missing_content_range_is_400(self, env):
        client, *_ = env
        _open(client)
        assert client.patch(f"/api/v1/uploads/{FILE_HASH}", content=DATA).status_code == 400

    def test_malformed_hash_is_422(self, env):
        client, *_ = env
        r = client.get("/api/v1/uploads/not-a-hash", params={"filename": "a.wav", "total_size": 1})
        assert r.status_code == 422

    def test_new_session_rejected_when_queue_full(self, env):
        from copernicus.exceptions import QueueFullError

        client, store, *_ = env

        def full():
            raise QueueFullError("队列已满")

        store.ensure_capacity = full
        assert _open(client).status_code == 429

    def test_resuming_existing_session_allowed_when_queue_full(self, env):
        from copernicus.exceptions import QueueFullError

        client, store, *_ = env
        _open(client)
        _put(client, 0, DATA[:40])

        def full():
            raise QueueFullError("队列已满")

        store.ensure_capacity = full
        assert _open(client).json()["offset"] == 40


class TestFinalChunkHandling:
    def test_queue_full_at_final_chunk_leaves_it_retryable(self, env):
        from copernicus.exceptions import QueueFullError

        client, store, sessions, _ = env
        _open(client)
        _put(client, 0, DATA[:60])

        def full():
            raise QueueFullError("队列已满")

        real = store.ensure_capacity
        store.ensure_capacity = full
        r = _put(client, 60, DATA[60:])
        assert r.status_code == 429
        assert sessions.get_session(FILE_HASH)["received_bytes"] == 60  # 末块没有落盘

        store.ensure_capacity = real  # 队列腾出空位后原样重传
        r = _put(client, 60, DATA[60:])
        assert r.status_code == 200 and r.json()["complete"] is True

    def test_submit_rejection_after_hashing_rolls_the_chunk_back(self, env):
        from unittest.mock import AsyncMock

        from copernicus.exceptions import QueueFullError

        client, store, sessions, _ = env
        _open(client)
        _put(client, 0, DATA[:60])
        store.submit_standard_minutes = AsyncMock(side_effect=QueueFullError("队列已满"))

        assert _put(client, 60, DATA[60:]).status_code == 429
        assert sessions.get_session(FILE_HASH)["received_bytes"] == 60

    def test_oversized_chunk_is_rejected_by_declared_length(self, env, monkeypatch):
        import copernicus.routers.upload as upload_module

        client, *_ = env
        _open(client)
        monkeypatch.setattr(upload_module, "_MAX_CHUNK_BYTES", 10)
        assert _put(client, 0, DATA[:60]).status_code == 413

    def test_hotword_limits_apply_to_chunked_sessions(self, env):
        client, *_ = env
        r = client.get(
            f"/api/v1/uploads/{FILE_HASH}",
            params={"filename": "a.wav", "total_size": 10, "hotwords": ["x" * 101]},
        )
        assert r.status_code == 422

    def test_final_chunk_moves_the_file_into_the_task_dir(self, env):
        client, _, sessions, persistence = env
        _open(client)
        _put(client, 0, DATA[:60])
        task_id = _put(client, 60, DATA[60:]).json()["task_id"]

        assert persistence.find_audio(task_id).read_bytes() == DATA
        assert sessions.get_session(FILE_HASH) is None
