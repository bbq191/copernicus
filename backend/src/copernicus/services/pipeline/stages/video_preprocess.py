"""Stage: Video preprocessing -- extract audio track from video file.

When the input file is a video, this stage extracts the audio track as
16 kHz mono WAV (applying the same enhancement filters when enabled),
reuses the video already persisted by the router, and sets
``ctx.media_type = "video"`` so downstream stages can branch.

Author: afu
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from copernicus.config import Settings
from copernicus.exceptions import AudioProcessingError
from copernicus.services.pipeline.base import PipelineContext
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
        # 复用 router 已保存到 task 目录的视频文件
        video_path = self._persistence.find_video(ctx.task_id)
        if video_path is None:
            raise RuntimeError(
                f"Video not found in task dir for {ctx.task_id}; "
                "router should have persisted it before pipeline starts."
            )

        # 提取的 WAV 也放在 task 目录内
        wav_path = self._persistence.task_dir(ctx.task_id) / "extracted.wav"

        await asyncio.to_thread(
            self._extract_audio, video_path, wav_path, self._audio_enhance
        )

        ctx.wav_path = wav_path
        ctx.video_path = video_path
        ctx.media_type = "video"
        logger.info("Video audio extracted to: %s", wav_path)
        return ctx

    @staticmethod
    def _extract_audio(
        video_path: Path, output_path: Path, audio_enhance: bool
    ) -> None:
        """Extract audio from video via ffmpeg (runs in thread)."""
        try:
            if audio_enhance:
                cmd = [
                    "ffmpeg", "-y",
                    "-i", str(video_path),
                    "-af", "highpass=f=200,afftdn=nf=-25,dynaudnorm=p=0.9:m=10:s=3",
                    "-ar", "16000",
                    "-ac", "1",
                    "-acodec", "pcm_s16le",
                    "-f", "wav",
                    str(output_path),
                ]
            else:
                cmd = [
                    "ffmpeg", "-y",
                    "-i", str(video_path),
                    "-ar", "16000",
                    "-ac", "1",
                    "-acodec", "pcm_s16le",
                    "-f", "wav",
                    str(output_path),
                ]

            logger.info("Extracting audio from video (enhance=%s)", audio_enhance)
            result = subprocess.run(cmd, capture_output=True)
            if result.returncode != 0:
                raise AudioProcessingError(
                    f"ffmpeg audio extraction failed (code {result.returncode}): "
                    f"{result.stderr.decode()}"
                )
            logger.info("Audio extraction completed.")
        except FileNotFoundError:
            raise AudioProcessingError(
                "ffmpeg not found. Please install ffmpeg and ensure it is on PATH."
            )
