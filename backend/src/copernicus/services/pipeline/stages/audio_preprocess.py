"""Stage: Audio preprocessing (format conversion + loudnorm)."""

import logging

from copernicus.services.audio import AudioService
from copernicus.services.persistence import PersistenceService
from copernicus.services.pipeline.base import PipelineContext, ProgressCallback

logger = logging.getLogger(__name__)


class AudioPreprocessStage:
    name = "audio_preprocess"

    def __init__(self, audio_service: AudioService, persistence: PersistenceService) -> None:
        self._audio = audio_service
        self._persistence = persistence

    def should_run(self, ctx: PipelineContext) -> bool:
        return ctx.media_path is not None and ctx.wav_path is None

    async def execute(
        self,
        ctx: PipelineContext,
        on_progress: ProgressCallback | None = None,
    ) -> PipelineContext:
        if ctx.media_path is None:
            raise RuntimeError("media_path is None in AudioPreprocessStage")
        logger.info("Audio preprocessing starting for: %s", ctx.filename)
        # 转换结果放在任务目录内：ASR 后会删除，异常中断时也随任务目录一起被清理
        output = self._persistence.task_dir(ctx.task_id) / "processed.wav"
        ctx.wav_path = await self._audio.extract_wav(ctx.media_path, output)
        logger.info("Audio preprocessed to: %s", ctx.wav_path)
        return ctx
