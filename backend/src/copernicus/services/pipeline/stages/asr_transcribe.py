"""Stage: ASR transcription. GPU 独占与"使用中不可卸载"由 ModelManager 的使用锁保证。"""

import asyncio
import logging

from copernicus.services.asr import ASRResult
from copernicus.services.audio import AudioService
from copernicus.services.model_manager import ModelManager
from copernicus.services.pipeline.base import PipelineContext, ProgressCallback

logger = logging.getLogger(__name__)


class ASRTranscribeStage:
    name = "asr_transcribe"

    def __init__(self, model_manager: ModelManager, audio_service: AudioService) -> None:
        self._models = model_manager
        self._audio = audio_service

    def should_run(self, ctx: PipelineContext) -> bool:
        return ctx.wav_path is not None

    async def execute(
        self,
        ctx: PipelineContext,
        on_progress: ProgressCallback | None = None,
    ) -> PipelineContext:
        if ctx.wav_path is None:
            raise RuntimeError("wav_path is None in ASRTranscribeStage")
        use_ts = ctx.sentence_timestamp
        logger.info("Starting ASR transcription (sentence_timestamp=%s)...", use_ts)

        asr_result = await self._transcribe_uninterruptibly(ctx, use_ts)

        ctx.asr_result = asr_result
        ctx.segments = list(asr_result.segments)
        logger.info(
            "ASR completed: %d segments, %d chars, speakers: %s",
            len(asr_result.segments),
            len(asr_result.text),
            sorted(set(s.speaker for s in asr_result.segments))
            if asr_result.segments
            else "N/A",
        )
        return ctx

    async def _transcribe_uninterruptibly(self, ctx: PipelineContext, use_ts: bool) -> ASRResult:
        """ASR 跑在线程里，无法被取消。

        直接 await 时，任务被取消（超时、关停）会让协程退出、模型锁随之释放，
        而线程仍在占用 GPU，下一个排队任务立刻拿到锁再起一个线程，两路推理并行有 OOM 风险。
        所以把"持锁 + 推理"放进一个独立任务，外层被取消时它继续运行到线程结束才释放锁。
        """
        started = False

        async def guarded() -> ASRResult:
            nonlocal started
            try:
                async with self._models.use("asr") as asr:
                    started = True
                    return await asyncio.to_thread(asr.transcribe, ctx.wav_path, ctx.hotwords, use_ts)
            finally:
                try:
                    self._audio.cleanup(ctx.wav_path)
                except Exception as e:
                    logger.warning("Audio cleanup failed for %s: %s", ctx.wav_path, e)

        inner = asyncio.ensure_future(guarded())
        try:
            return await asyncio.shield(inner)
        except asyncio.CancelledError:
            if not started:
                inner.cancel()  # 还在排队、没碰 GPU：直接放弃
            else:
                logger.warning("Task cancelled while ASR is running; waiting for the thread to finish")
                inner.add_done_callback(_consume_outcome)
            raise


def _consume_outcome(task: "asyncio.Future") -> None:
    """外层已放弃等待：取走结果/异常，避免 'exception was never retrieved' 警告。"""
    if not task.cancelled():
        task.exception()
