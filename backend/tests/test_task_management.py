from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from copernicus.config import Settings
from copernicus.error_handlers import register_error_handlers
from copernicus.routers.task import router as task_router
from copernicus.schemas.task import TaskStatus
from copernicus.schemas.transcription import TranscriptEntrySchema, TranscriptResponse
from copernicus.services.persistence import PersistenceService
from copernicus.services.task_store import TaskInfo, TaskStore
from copernicus.services.transcript_edit import apply_speaker_renames, apply_text_edits

TID_A = "a" * 32
TID_B = "b" * 32


def _entry(i: int, speaker: str, text: str) -> TranscriptEntrySchema:
    return TranscriptEntrySchema(
        timestamp=f"00:0{i}",
        timestamp_ms=i * 1000,
        end_ms=i * 1000 + 900,
        speaker=speaker,
        text=text,
        text_corrected=text,
    )


def _transcript() -> TranscriptResponse:
    return TranscriptResponse(
        transcript=[
            _entry(0, "Speaker 1", "第一句"),
            _entry(1, "Speaker 2", "第二句"),
            _entry(2, "Speaker 1", "第三句"),
        ],
        processing_time_ms=1.0,
    )


class TestTranscriptEditFunctions:
    def test_text_edit_changes_corrected_only(self):
        result, changed = apply_text_edits(_transcript(), {1: "改后"})
        assert changed == 1
        assert result.transcript[1].text_corrected == "改后"
        assert result.transcript[1].text == "第二句"

    def test_out_of_range_and_unchanged_ignored(self):
        _, changed = apply_text_edits(_transcript(), {99: "x", 0: "第一句", -1: "y"})
        assert changed == 0

    def test_rename_and_merge_speakers(self):
        result, affected = apply_speaker_renames(
            _transcript(), {"Speaker 1": "张三", "Speaker 2": "张三"}
        )
        assert affected == 3
        assert {e.speaker for e in result.transcript} == {"张三"}

    def test_rename_only_affects_named_speakers(self):
        result, affected = apply_speaker_renames(_transcript(), {"Speaker 2": "李四"})
        assert affected == 1
        assert [e.speaker for e in result.transcript] == ["Speaker 1", "李四", "Speaker 1"]


@pytest.fixture
def persistence(tmp_path) -> PersistenceService:
    return PersistenceService(tmp_path)


@pytest.fixture
def store(persistence) -> TaskStore:
    return TaskStore(MagicMock(), persistence, Settings())


@pytest.fixture
def api(store) -> TestClient:
    app = FastAPI()
    app.state.task_store = store
    app.include_router(task_router)
    register_error_handlers(app)
    return TestClient(app)


def _seed(persistence, task_id, *, created_at, filename="a.wav", done=True):
    persistence.save_meta(
        task_id, filename=filename, file_hash=task_id, audio_suffix=".wav"
    )
    # 固定创建时间以便断言排序
    persistence.update_meta(task_id, created_at=created_at)
    (persistence.task_dir(task_id) / "audio.wav").write_bytes(b"audio")
    if done:
        persistence.save_json(task_id, "transcript.json", _transcript())


class TestListTasks:
    def test_sorted_newest_first_with_statuses(self, api, persistence, store):
        _seed(persistence, TID_A, created_at="2026-01-01T00:00:00+00:00")
        _seed(persistence, TID_B, created_at="2026-02-01T00:00:00+00:00", done=False)

        body = api.get("/api/v1/tasks").json()

        assert [t["task_id"] for t in body["tasks"]] == [TID_B, TID_A]
        assert body["tasks"][0]["status"] == "failed"
        assert body["tasks"][1]["status"] == "completed"
        assert body["total"] == 2

    def test_limit_truncates_but_reports_total(self, api, persistence):
        _seed(persistence, TID_A, created_at="2026-01-01T00:00:00+00:00")
        _seed(persistence, TID_B, created_at="2026-02-01T00:00:00+00:00")

        body = api.get("/api/v1/tasks?limit=1").json()

        assert len(body["tasks"]) == 1
        assert body["total"] == 2

    def test_name_prefers_rename_then_title_then_filename(self, api, persistence):
        _seed(persistence, TID_A, created_at="2026-01-01T00:00:00+00:00", filename="raw.wav")
        assert api.get("/api/v1/tasks").json()["tasks"][0]["name"] == "raw.wav"

        persistence.save_data(TID_A, "evaluation.json", {"title": "季度复盘会", "formatted_content": ""})
        assert api.get("/api/v1/tasks").json()["tasks"][0]["name"] == "季度复盘会"

        assert api.patch(f"/api/v1/tasks/{TID_A}", json={"name": " 我的会议 "}).status_code == 204
        assert api.get("/api/v1/tasks").json()["tasks"][0]["name"] == "我的会议"

    def test_rename_unknown_task_is_404(self, api):
        assert api.patch(f"/api/v1/tasks/{TID_A}", json={"name": "x"}).status_code == 404

    def test_invalidated_task_hidden(self, api, persistence, store):
        _seed(persistence, TID_A, created_at="2026-01-01T00:00:00+00:00")
        store.restore_from_disk()
        assert api.delete(f"/api/v1/tasks/{TID_A}").status_code == 204

        assert api.get("/api/v1/tasks").json()["tasks"] == []


class TestPurge:
    def test_purge_removes_files_memory_and_hash(self, api, persistence, store):
        _seed(persistence, TID_A, created_at="2026-01-01T00:00:00+00:00")
        store.restore_from_disk()

        assert api.delete(f"/api/v1/tasks/{TID_A}?purge=true").status_code == 204

        assert not (persistence._upload_dir / TID_A).exists()
        assert store.get(TID_A) is None
        assert store.lookup_by_hash(TID_A) is None

    def test_plain_delete_keeps_files(self, api, persistence, store):
        _seed(persistence, TID_A, created_at="2026-01-01T00:00:00+00:00")
        store.restore_from_disk()

        assert api.delete(f"/api/v1/tasks/{TID_A}").status_code == 204

        assert (persistence._upload_dir / TID_A).exists()

    def test_purge_running_task_rejected(self, api, persistence, store):
        _seed(persistence, TID_A, created_at="2026-01-01T00:00:00+00:00", done=False)
        running = TaskInfo(TID_A)
        running.status = TaskStatus.PROCESSING_ASR
        store._tasks[TID_A] = running

        assert api.delete(f"/api/v1/tasks/{TID_A}?purge=true").status_code == 409
        assert (persistence._upload_dir / TID_A).exists()

    def test_purge_unknown_is_404(self, api):
        assert api.delete(f"/api/v1/tasks/{TID_A}?purge=true").status_code == 404


class TestProofreadingEndpoints:
    def _completed(self, persistence, store):
        _seed(persistence, TID_A, created_at="2026-01-01T00:00:00+00:00")
        store.restore_from_disk()

    def test_edit_persists_and_refreshes_in_memory_result(self, api, persistence, store):
        self._completed(persistence, store)

        r = api.patch(
            f"/api/v1/tasks/{TID_A}/transcript",
            json={"edits": [{"index": 0, "text_corrected": "修订后"}]},
        )

        assert r.json() == {"updated": 1}
        on_disk = persistence.load_json(TID_A, "transcript.json")
        assert on_disk["transcript"][0]["text_corrected"] == "修订后"
        # 状态接口返回的内存结果也应同步，否则刷新后会看到旧文本
        assert store.get(TID_A).result.transcript[0].text_corrected == "修订后"

    def test_rename_speakers_persists(self, api, persistence, store):
        self._completed(persistence, store)

        r = api.patch(
            f"/api/v1/tasks/{TID_A}/speakers",
            json={"renames": {"Speaker 1": "  张三  "}},
        )

        assert r.json() == {"updated": 2}
        speakers = [e["speaker"] for e in persistence.load_json(TID_A, "transcript.json")["transcript"]]
        assert speakers == ["张三", "Speaker 2", "张三"]

    def test_blank_speaker_name_rejected(self, api, persistence, store):
        self._completed(persistence, store)
        r = api.patch(f"/api/v1/tasks/{TID_A}/speakers", json={"renames": {"Speaker 1": "   "}})
        assert r.status_code == 422

    def test_empty_edit_list_rejected(self, api, persistence, store):
        self._completed(persistence, store)
        assert api.patch(f"/api/v1/tasks/{TID_A}/transcript", json={"edits": []}).status_code == 422

    def test_edit_on_unfinished_task_is_409(self, api, persistence, store):
        _seed(persistence, TID_B, created_at="2026-01-01T00:00:00+00:00", done=False)
        store.restore_from_disk()  # 恢复为 failed
        r = api.patch(
            f"/api/v1/tasks/{TID_B}/transcript",
            json={"edits": [{"index": 0, "text_corrected": "x"}]},
        )
        assert r.status_code == 409

    def test_edit_unknown_task_is_404(self, api):
        r = api.patch(
            f"/api/v1/tasks/{TID_A}/transcript",
            json={"edits": [{"index": 0, "text_corrected": "x"}]},
        )
        assert r.status_code == 404


class TestReadPathsDoNotCreateDirectories:
    def test_load_json_and_has_file_for_unknown_task_leave_no_trace(self, tmp_path):
        persistence = PersistenceService(tmp_path)
        unknown = "e" * 32

        assert persistence.load_json(unknown, "transcript.json") is None
        assert persistence.has_file(unknown, "meta.json") is False
        assert persistence.find_audio(unknown) is None
        assert not (tmp_path / unknown).exists()
