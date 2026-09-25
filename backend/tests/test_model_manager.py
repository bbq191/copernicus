"""ModelManager 使用锁与 ASR 阶段的取消语义。"""

import asyncio
import threading
from unittest.mock import MagicMock

import pytest

from copernicus.services.model_manager import ModelManager
from copernicus.services.pipeline.base import PipelineContext
from copernicus.services.pipeline.stages.asr_transcribe import ASRTranscribeStage


def _manager() -> tuple[ModelManager, dict[str, list[str]]]:
    events: dict[str, list[str]] = {"log": []}
    m = ModelManager()
    for name in ("asr", "tts"):
        m.register_loader(
            name,
            loader=lambda n=name: events["log"].append(f"load:{n}") or n,
            unloader=lambda _model, n=name: events["log"].append(f"unload:{n}"),
            vram_estimate_gb=4.0,
        )
    return m, events


async def _tick(n: int = 5) -> None:
    for _ in range(n):
        await asyncio.sleep(0)


class TestUseLock:
    async def test_loads_on_demand_and_keeps_the_model_afterwards(self):
        m, ev = _manager()
        async with m.use("asr") as model:
            assert model == "asr"
        assert m.loaded_models == ["asr"] and ev["log"] == ["load:asr"]

    async def test_unload_waits_for_the_current_user(self):
        m, ev = _manager()
        entered, release = asyncio.Event(), asyncio.Event()

        async def user():
            async with m.use("asr"):
                entered.set()
                await release.wait()

        task = asyncio.create_task(user())
        await entered.wait()
        unloading = asyncio.create_task(m.unload("asr"))
        await _tick()
        assert not unloading.done() and "unload:asr" not in ev["log"]  # 使用中不可卸载

        release.set()
        await asyncio.gather(task, unloading)
        assert m.loaded_models == []

    async def test_queued_user_reloads_after_an_unload_that_was_queued_before_it(self):
        m, ev = _manager()
        async with m.use("asr"):
            pass
        await m.unload("asr")
        async with m.use("asr"):
            pass
        assert ev["log"] == ["load:asr", "unload:asr", "load:asr"]

    async def test_exclusive_evicts_other_models_and_unload_after_releases(self):
        m, ev = _manager()
        async with m.use("asr"):
            pass
        async with m.use("tts", exclusive=True, unload_after=True):
            assert m.loaded_models == ["tts"]
        assert m.loaded_models == []
        assert ev["log"] == ["load:asr", "unload:asr", "load:tts", "unload:tts"]

    async def test_exclusive_waits_for_a_running_asr_user(self):
        m, ev = _manager()
        entered, release = asyncio.Event(), asyncio.Event()

        async def asr_user():
            async with m.use("asr"):
                entered.set()
                await release.wait()

        user = asyncio.create_task(asr_user())
        await entered.wait()
        tts = asyncio.create_task(_use_tts(m))
        await _tick()
        assert not tts.done() and "load:tts" not in ev["log"]

        release.set()
        await asyncio.gather(user, tts)
        assert ev["log"].index("unload:asr") < ev["log"].index("load:tts")


async def _use_tts(m: ModelManager):
    async with m.use("tts", exclusive=True):
        pass


class _BlockingASR:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    def transcribe(self, wav, hotwords, use_ts):
        self.calls += 1
        self.started.set()
        self.release.wait(timeout=5)
        return MagicMock(segments=[], text="")


def _stage(asr: _BlockingASR):
    m = ModelManager()
    m.register_loader("asr", loader=lambda: asr)
    audio = MagicMock()
    return ASRTranscribeStage(m, audio), m, audio


def _ctx(tmp_path) -> PipelineContext:
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"x")
    return PipelineContext(wav_path=wav)


class TestAsrStageCancellation:
    async def test_cancelled_task_keeps_the_model_locked_until_the_thread_ends(self, tmp_path):
        asr = _BlockingASR()
        stage, manager, audio = _stage(asr)

        running = asyncio.create_task(stage.execute(_ctx(tmp_path)))
        while not asr.started.is_set():
            await asyncio.sleep(0.005)
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running

        # 外层已取消，但线程还在跑：下一个使用者不能拿到模型
        second_entered = asyncio.Event()

        async def second():
            async with manager.use("asr"):
                second_entered.set()

        follower = asyncio.create_task(second())
        await asyncio.sleep(0.05)
        assert not second_entered.is_set()
        audio.cleanup.assert_not_called()

        asr.release.set()
        await asyncio.wait_for(follower, timeout=2)
        assert second_entered.is_set()
        audio.cleanup.assert_called_once()  # 线程结束后才清理 wav

    async def test_task_cancelled_while_queued_never_touches_the_gpu(self, tmp_path):
        asr = _BlockingASR()
        stage, manager, _ = _stage(asr)
        holder_in, holder_out = asyncio.Event(), asyncio.Event()

        async def holder():
            async with manager.use("asr"):
                holder_in.set()
                await holder_out.wait()

        h = asyncio.create_task(holder())
        await holder_in.wait()

        queued = asyncio.create_task(stage.execute(_ctx(tmp_path)))
        await _tick()
        queued.cancel()
        with pytest.raises(asyncio.CancelledError):
            await queued

        holder_out.set()
        await h
        await _tick()
        assert asr.calls == 0


class TestAsrStageAnnouncements:
    async def test_idle_gpu_goes_straight_to_transcribing(self, tmp_path):
        asr = _BlockingASR()
        asr.release.set()
        stage, _, _ = _stage(asr)
        phases: list[str] = []
        ctx = _ctx(tmp_path)
        ctx.on_phase = phases.append

        await stage.execute(ctx)
        assert phases == ["asr_transcribe"]

    async def test_busy_gpu_announces_queueing_before_transcribing(self, tmp_path):
        asr = _BlockingASR()
        asr.release.set()
        stage, manager, _ = _stage(asr)
        phases: list[str] = []
        ctx = _ctx(tmp_path)
        ctx.on_phase = phases.append
        holder_in, holder_out = asyncio.Event(), asyncio.Event()

        async def holder():
            async with manager.use("asr"):
                holder_in.set()
                await holder_out.wait()

        h = asyncio.create_task(holder())
        await holder_in.wait()
        queued = asyncio.create_task(stage.execute(ctx))
        await _tick()
        assert phases == ["asr_queued"]  # 排队期间尚未开始识别

        holder_out.set()
        await asyncio.gather(h, queued)
        assert phases == ["asr_queued", "asr_transcribe"]
