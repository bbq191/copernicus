"""Stage: Video preprocessing -- extract audio track from video file."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from copernicus.config import Settings
from copernicus.exceptions import AudioProcessingError
from copernicus.services.pipeline.base import PipelineContext
from copernicus.utils.ffmpeg import run as ffmpeg_run
from copernicus.utils.types import ProgressCallback

if TYPE_CHECKING:
    from copernicus.services.persistence import PersistenceService

logger = logging.getLogger(__name__)


class VideoPreprocessStage:
    name = "video_preprocess"

    def __init__(self, settings: Settings, persistence: PersistenceService) -> None:
        self._video_exts = {
            e.strip().lower()
            for e in settings.video_extensions.split(",")
            if e.strip()
        }
        self._audio_enhance = settings.audio_enhance
        self._persistence = persistence

    def should_run(self, ctx: PipelineContext) -> bool:
        if not ctx.filename:
            return False
        return Path(ctx.filename).suffix.lower() in self._video_exts

    async def execute(
        self,
        ctx: PipelineContext,
        on_progress: ProgressCallback | None = None,
    ) -> PipelineContext:
        ctx.audio_bytes = None  # 视频路径已落盘，无需再持有原始字节
        video_path = self._persistence.find_video(ctx.task_id)
        if video_path is None:
            raise RuntimeError(
                f"Video not found in task dir for {ctx.task_id}; "
                "router should have persisted it before pipeline starts."
            )

        wav_path = self._persistence.task_dir(ctx.task_id) / "extracted.wav"
        await self._extract_audio(video_path, wav_path, self._audio_enhance)

        ctx.wav_path = wav_path
        ctx.video_path = video_path
        ctx.media_type = "video"
        logger.info("Video audio extracted to: %s", wav_path)
        return ctx

    @staticmethod
    async def _extract_audio(
        video_path: Path, output_path: Path, audio_enhance: bool
    ) -> None:
        if audio_enhance:
            cmd = [
                "ffmpeg", "-y",
                "-i", str(video_path),
                "-af", "highpass=f=200,afftdn=nf=-25,dynaudnorm=p=0.9:m=10:s=3",
                "-ar", "16000", "-ac", "1",
                "-acodec", "pcm_s16le", "-f", "wav",
                str(output_path),
            ]
        else:
            cmd = [
                "ffmpeg", "-y",
                "-i", str(video_path),
                "-ar", "16000", "-ac", "1",
                "-acodec", "pcm_s16le", "-f", "wav",
                str(output_path),
            ]
        logger.info("Extracting audio from video (enhance=%s)", audio_enhance)
        rc, stderr = await ffmpeg_run(cmd, timeout=600)
        if rc != 0:
            raise AudioProcessingError(f"ffmpeg audio extraction failed (code {rc}): {stderr}")
        logger.info("Audio extraction completed.")
