"""Stage: ASR transcription with asyncio.Lock for GPU exclusion."""

import asyncio
import logging

from copernicus.services.asr import ASRService
from copernicus.services.audio import AudioService
from copernicus.services.pipeline.base import PipelineContext, ProgressCallback

logger = logging.getLogger(__name__)


class ASRTranscribeStage:
    name = "asr_transcribe"

    def __init__(
        self,
        asr_service: ASRService,
        audio_service: AudioService,
        asr_lock: asyncio.Lock,
    ) -> None:
        self._asr = asr_service
        self._audio = audio_service
        self._lock = asr_lock

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
        try:
            async with self._lock:
                asr_result = await asyncio.to_thread(
                    self._asr.transcribe, ctx.wav_path, ctx.hotwords, use_ts
                )
        finally:
            self._audio.cleanup(ctx.wav_path)

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
