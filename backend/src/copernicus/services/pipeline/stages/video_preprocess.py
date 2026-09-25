"""Stage: Video preprocessing -- extract audio track from video file."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from copernicus.config import Settings
from copernicus.services.audio import AudioService
from copernicus.services.pipeline.base import PipelineContext
from copernicus.utils.types import ProgressCallback

if TYPE_CHECKING:
    from copernicus.services.persistence import PersistenceService

logger = logging.getLogger(__name__)


class VideoPreprocessStage:
    name = "video_preprocess"

    def __init__(
        self, settings: Settings, persistence: PersistenceService, audio_service: AudioService
    ) -> None:
        self._video_exts = settings.video_extensions_set
        self._persistence = persistence
        self._audio = audio_service

    def should_run(self, ctx: PipelineContext) -> bool:
        return bool(ctx.filename) and Path(ctx.filename).suffix.lower() in self._video_exts

    async def execute(
        self,
        ctx: PipelineContext,
        on_progress: ProgressCallback | None = None,
    ) -> PipelineContext:
        if ctx.media_path is None:
            raise RuntimeError("media_path is None in VideoPreprocessStage")

        wav_path = self._persistence.task_dir(ctx.task_id) / "extracted.wav"
        logger.info("Extracting audio from video %s", ctx.media_path.name)
        await self._audio.extract_wav(ctx.media_path, wav_path)

        ctx.wav_path = wav_path
        ctx.video_path = ctx.media_path
        ctx.media_type = "video"
        logger.info("Video audio extracted to: %s", wav_path)
        return ctx
