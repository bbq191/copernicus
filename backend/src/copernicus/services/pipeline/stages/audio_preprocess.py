"""Stage: Audio preprocessing (format conversion + loudnorm)."""

import logging

from copernicus.services.audio import AudioService
from copernicus.services.pipeline.base import PipelineContext, ProgressCallback

logger = logging.getLogger(__name__)


class AudioPreprocessStage:
    name = "audio_preprocess"

    def __init__(self, audio_service: AudioService) -> None:
        self._audio = audio_service

    def should_run(self, ctx: PipelineContext) -> bool:
        return ctx.audio_bytes is not None

    async def execute(
        self,
        ctx: PipelineContext,
        on_progress: ProgressCallback | None = None,
    ) -> PipelineContext:
        if ctx.audio_bytes is None:
            raise RuntimeError("audio_bytes is None in AudioPreprocessStage")
        logger.info("Audio preprocessing starting for: %s", ctx.filename)
        ctx.wav_path = await self._audio.preprocess(ctx.audio_bytes, ctx.filename)
        logger.info("Audio preprocessed to: %s", ctx.wav_path)
        return ctx
