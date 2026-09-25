"""SynthesisService：任务状态收敛、原子产物、关停取消。"""

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest
import soundfile as sf

import copernicus.services.tts as tts
from copernicus.config import Settings
from copernicus.exceptions import TaskBusyError
from copernicus.schemas.transcription import TranscriptEntrySchema, TranscriptResponse
from copernicus.services.model_manager import ModelManager
from copernicus.services.persistence import PersistenceService
from copernicus.services.synthesis import SynthesisService, build_rewrite_prompt
from copernicus.services.task_store import TaskStore

TID = "a" * 32


def _transcript() -> TranscriptResponse:
    entries = [
        TranscriptEntrySchema(
            timestamp="00:00", timestamp_ms=0, end_ms=1000, speaker=spk, text="你好世界", text_corrected="你好世界"
        )
        for spk in ("A", "B")
    ]
    return TranscriptResponse(transcript=entries, processing_time_ms=1.0)


@pytest.fixture
def env(tmp_path, monkeypatch):
    persistence = PersistenceService(tmp_path)
    persistence.task_dir(TID)
    store = TaskStore(MagicMock(), persistence, Settings())
    models = ModelManager()
    models.register_loader("tts", loader=lambda: object())
    service = SynthesisService(store, models, Settings(tts_rewrite_enabled=False))

    def fake_synthesize(chunks, model, voice_map, params, work_dir: Path):
        part = work_dir / "p0.wav"
        sf.write(str(part), np.zeros(2400, dtype=np.float32), 24000)
        return [part]

    async def fake_concat(parts, dest: Path):
        dest.write_bytes(b"MP3DATA")

    monkeypatch.setattr(tts, "synthesize_chunks_batched", fake_synthesize)
    monkeypatch.setattr(tts, "concat_parts_to_mp3", fake_concat)
    return service, store, persistence, models


async def _finish(service: SynthesisService) -> None:
    await asyncio.gather(*service._handles)


class TestSynthesisService:
    async def test_success_produces_the_mp3_and_a_completed_job(self, env):
        service, store, persistence, models = env
        await service.start(TID, _transcript())
        await _finish(service)

        job = store.get_synthesis_job(TID)
        assert job.status == "completed" and job.duration_ms == pytest.approx(100, abs=1)
        assert (persistence.path_of(TID) / "synthesis.mp3").read_bytes() == b"MP3DATA"
        assert not list(persistence.path_of(TID).glob("*.partial.mp3"))
        assert persistence.load_json(TID, "synthesis_result.json")["duration_ms"] > 0
        assert models.loaded_models == []  # 合成结束立即卸载 TTS

    async def test_encoding_failure_leaves_no_partial_or_final_file(self, env, monkeypatch):
        service, store, persistence, _ = env

        async def failing_concat(parts, dest: Path):
            dest.write_bytes(b"half")
            raise RuntimeError("ffmpeg died")

        monkeypatch.setattr(tts, "concat_parts_to_mp3", failing_concat)
        await service.start(TID, _transcript())
        await _finish(service)

        assert store.get_synthesis_job(TID).status == "failed"
        assert not (persistence.path_of(TID) / "synthesis.mp3").exists()
        assert not list(persistence.path_of(TID).glob("*.partial.mp3"))

    async def test_preparation_failure_does_not_leave_the_job_running(self, env, monkeypatch):
        service, store, *_ = env
        service._settings = Settings(tts_rewrite_enabled=True)

        async def broken_rewrite(chunks):
            raise RuntimeError("LLM 不可达")

        monkeypatch.setattr(service, "_rewrite", broken_rewrite)
        with pytest.raises(RuntimeError):
            await service.start(TID, _transcript())

        assert store.get_synthesis_job(TID).status == "failed"
        service._settings = Settings(tts_rewrite_enabled=False)
        await service.start(TID, _transcript())  # 不再被 409 卡住
        await _finish(service)
        assert store.get_synthesis_job(TID).status == "completed"

    async def test_second_submit_while_running_is_rejected(self, env, monkeypatch):
        service, *_ = env
        gate = asyncio.Event()
        real = tts.synthesize_chunks_batched

        def slow(*args, **kwargs):
            # 在线程里等到测试放行；此时第一个任务持有 running 状态
            asyncio.run_coroutine_threadsafe(gate.wait(), loop).result(timeout=5)
            return real(*args, **kwargs)

        loop = asyncio.get_running_loop()
        monkeypatch.setattr(tts, "synthesize_chunks_batched", slow)
        await service.start(TID, _transcript())
        with pytest.raises(TaskBusyError):
            await service.start(TID, _transcript())
        gate.set()
        await _finish(service)

    async def test_cancel_all_marks_the_job_failed(self, env, monkeypatch):
        service, store, *_ = env
        started = asyncio.Event()

        async def hang(parts, dest):
            started.set()
            await asyncio.sleep(60)

        monkeypatch.setattr(tts, "concat_parts_to_mp3", hang)
        await service.start(TID, _transcript())
        await started.wait()
        await service.cancel_all()

        assert store.get_synthesis_job(TID).status == "failed"
        assert service._handles == set()


class TestRewritePrompt:
    @pytest.mark.parametrize("energy,marker", [(1, "平静"), (4, "口语化"), (7, "热情"), (9, "带货主播")])
    def test_style_follows_energy_level(self, energy, marker):
        assert marker in build_rewrite_prompt("原文", energy)


class TestSynthesizeRoute:
    def test_request_body_is_optional(self, tmp_path):
        from unittest.mock import AsyncMock

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from copernicus.routers.synthesis import router

        persistence = PersistenceService(tmp_path)
        persistence.save_data(
            TID, "transcript.json", _transcript().model_dump(),
        )
        store = MagicMock(spec=TaskStore)
        store.persistence = persistence
        store.has_active_llm_tasks.return_value = False
        service = MagicMock(spec=SynthesisService)
        service.start = AsyncMock()

        app = FastAPI()
        app.state.task_store = store
        app.state.synthesis = service
        app.include_router(router)
        client = TestClient(app)

        assert client.post(f"/api/v1/tasks/{TID}/synthesize").status_code == 202
        assert client.post(f"/api/v1/tasks/{TID}/synthesize", json={"voice_map": {"A": "7777"}}).status_code == 202
        overrides = [c.args[2] for c in service.start.await_args_list]
        assert overrides == [None, {"A": "7777"}]
