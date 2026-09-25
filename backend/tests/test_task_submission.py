"""任务提交流程：媒体先落盘再启动管线、失败不留幽灵任务、摘要失败不拖垮转写。"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from copernicus.config import Settings
from copernicus.schemas.task import TaskStatus
from copernicus.services.pipeline.base import TranscriptEntry, TranscriptResult
from copernicus.services.persistence import PersistenceService
from copernicus.services.task_store import TaskStore

FILE_HASH = "f" * 64


def _result() -> TranscriptResult:
    entry = TranscriptEntry(
        timestamp="00:00", timestamp_ms=0, end_ms=1000, speaker="Speaker 1", text="你好", text_corrected="你好"
    )
    return TranscriptResult(transcript=[entry], processing_time_ms=1.0)


@pytest.fixture
def persistence(tmp_path) -> PersistenceService:
    return PersistenceService(tmp_path)


def _store(persistence, *, evaluator=None) -> tuple[TaskStore, MagicMock]:
    pipeline = MagicMock()
    pipeline.process_transcript = AsyncMock(return_value=_result())
    return TaskStore(pipeline, persistence, Settings(), evaluator=evaluator), pipeline


def _upload(tmp_path, data: bytes = b"x" * 4096):
    source = tmp_path / "incoming.part"
    source.write_bytes(data)
    return source


class TestMediaOrdering:
    async def test_media_is_in_place_before_the_pipeline_starts(self, tmp_path, persistence):
        store, pipeline = _store(persistence)
        seen: dict = {}

        async def process(media_path, *args, **kwargs):
            seen["size"] = media_path.stat().st_size
            seen["name"] = media_path.name
            return _result()

        pipeline.process_transcript.side_effect = process
        source = _upload(tmp_path, b"y" * 8192)

        task_id = await store.submit_transcript(source, "meeting.wav", file_hash=FILE_HASH)
        await store._handles[task_id]

        assert seen == {"size": 8192, "name": "audio.wav"}
        assert not source.exists()  # 是移动而不是复制
        assert store.lookup_by_hash(FILE_HASH) == task_id
        assert store.get(task_id).status == TaskStatus.COMPLETED

    async def test_video_is_stored_under_video_name(self, tmp_path, persistence):
        store, pipeline = _store(persistence)
        task_id = await store.submit_transcript(_upload(tmp_path), "clip.MP4", file_hash=FILE_HASH)
        await store._handles[task_id]

        media = pipeline.process_transcript.call_args.args[0]
        assert media.name == "video.MP4" and persistence.find_video(task_id) == media
        assert persistence.load_meta(task_id)["media_type"] == "video"

    async def test_failed_persist_leaves_no_ghost_task(self, tmp_path, persistence, monkeypatch):
        store, _ = _store(persistence)
        monkeypatch.setattr(persistence, "adopt_media", MagicMock(side_effect=OSError("disk full")))

        with pytest.raises(OSError):
            await store.submit_transcript(_upload(tmp_path), "a.wav", file_hash=FILE_HASH)

        assert store._tasks == {}
        assert store.lookup_by_hash(FILE_HASH) is None
        assert [p for p in tmp_path.iterdir() if p.is_dir() and not p.name.startswith(".")] == []

    async def test_duplicate_arriving_during_persist_hits_the_placeholder(self, tmp_path, persistence):
        store, _ = _store(persistence)
        real_adopt = persistence.adopt_media

        def slow_adopt(*args, **kwargs):
            time.sleep(0.05)  # 在线程里模拟大文件落盘耗时
            return real_adopt(*args, **kwargs)

        persistence.adopt_media = slow_adopt  # type: ignore[method-assign]

        first = asyncio.create_task(store.submit_transcript(_upload(tmp_path), "a.wav", file_hash=FILE_HASH))
        await asyncio.sleep(0.01)  # 第一个提交已登记占位、正在落盘
        placeholder = store.lookup_by_hash(FILE_HASH)
        assert placeholder is not None

        task_id = await first
        await store._handles[task_id]
        assert placeholder == task_id


class TestSummaryIsolation:
    async def test_summary_failure_keeps_the_task_completed(self, tmp_path, persistence):
        evaluator = MagicMock()
        evaluator.evaluate = AsyncMock(side_effect=RuntimeError("LLM 不可用"))
        store, _ = _store(persistence, evaluator=evaluator)

        task_id = await store.submit_standard_minutes(_upload(tmp_path), "a.wav", file_hash=FILE_HASH)
        await store._handles[task_id]

        task = store.get(task_id)
        assert task.status == TaskStatus.COMPLETED and task.error is None
        assert persistence.has_file(task_id, "transcript.json")
        assert not persistence.has_file(task_id, "evaluation.json")
        assert store.lookup_by_hash(FILE_HASH) == task_id  # 同一文件重传仍复用，不重跑 ASR


class TestRerun:
    async def test_rerun_passes_the_stored_path_without_loading_it(self, tmp_path, persistence):
        store, pipeline = _store(persistence)
        task_id = await store.submit_transcript(_upload(tmp_path), "a.wav", file_hash=FILE_HASH)
        await store._handles[task_id]
        pipeline.process_transcript.reset_mock()

        store.rerun_transcript(task_id)
        await store._handles[task_id]

        media, filename = pipeline.process_transcript.call_args.args[:2]
        assert media == persistence.find_audio(task_id) and filename == "audio.wav"


class TestParentValidation:
    def test_unknown_parent_is_rejected_before_any_llm_work(self, tmp_path, persistence):
        from copernicus.exceptions import TaskNotFoundError

        store, _ = _store(persistence, evaluator=MagicMock())
        store._executor._compliance = MagicMock()

        with pytest.raises(TaskNotFoundError):
            store.submit_text_evaluation("文本", parent_task_id="9" * 32)
        with pytest.raises(TaskNotFoundError):
            store.submit_compliance_audit([], b"", "rules.csv", parent_task_id="9" * 32)
        assert store._tasks == {}


class TestCorrectionDegradationIsExposed:
    async def test_failed_correction_batches_reach_the_persisted_transcript(self, tmp_path, persistence):
        store, pipeline = _store(persistence)
        degraded = _result()
        degraded.correction_total_batches, degraded.correction_failed_batches = 4, 3
        pipeline.process_transcript.return_value = degraded

        task_id = await store.submit_transcript(_upload(tmp_path), "a.wav")
        await store._handles[task_id]

        saved = persistence.load_json(task_id, "transcript.json")
        assert (saved["correction_total_batches"], saved["correction_failed_batches"]) == (4, 3)

    async def test_old_transcripts_without_the_fields_still_load(self, tmp_path, persistence):
        from copernicus.schemas.transcription import TranscriptResponse

        old = {"transcript": [], "processing_time_ms": 1.0}
        assert TranscriptResponse.model_validate(old).correction_failed_batches == 0
