"""Stage: Keyframe extraction from video.

Extracts keyframes using ffmpeg (interval or scene-change strategy),
saves them under ``uploads/{task_id}/frames/``, and populates
``ctx.keyframes``.

Author: afu
"""

import asyncio
import json
import logging
import re
import subprocess
from pathlib import Path

from copernicus.config import Settings
from copernicus.services.persistence import PersistenceService
from copernicus.services.pipeline.base import PipelineContext
from copernicus.utils.types import ProgressCallback

logger = logging.getLogger(__name__)


class KeyframeExtractStage:
    name = "keyframe_extract"

    def __init__(self, settings: Settings, persistence: PersistenceService) -> None:
        self._strategy = settings.keyframe_strategy
        self._interval_s = settings.keyframe_interval_s
        self._scene_threshold = settings.keyframe_scene_threshold
        self._max_count = settings.keyframe_max_count
        self._fmt = settings.keyframe_format
        self._quality = settings.keyframe_quality
        self._persistence = persistence

    def should_run(self, ctx: PipelineContext) -> bool:
        return ctx.video_path is not None

    async def execute(
        self,
        ctx: PipelineContext,
        on_progress: ProgressCallback | None = None,
    ) -> PipelineContext:
        if ctx.video_path is None:
            raise RuntimeError("video_path is None in KeyframeExtractStage")

        task_id = ctx.task_id
        if not task_id:
            raise RuntimeError("task_id is empty in KeyframeExtractStage")
        frames_dir = self._persistence.frames_dir(task_id)

        if self._strategy == "scene":
            await asyncio.to_thread(
                self._extract_scene, ctx.video_path, frames_dir
            )
        else:
            await asyncio.to_thread(
                self._extract_interval, ctx.video_path, frames_dir
            )

        # Collect extracted frames sorted by name
        frame_files = sorted(frames_dir.glob(f"*.{self._fmt}"))

        # Enforce max count via uniform sampling
        if len(frame_files) > self._max_count:
            step = len(frame_files) / self._max_count
            sampled = [frame_files[int(i * step)] for i in range(self._max_count)]
            # Remove unsampled frames
            sampled_set = set(sampled)
            for f in frame_files:
                if f not in sampled_set:
                    f.unlink(missing_ok=True)
            frame_files = sampled

        # Build KeyFrame list (using schema dict to avoid hard import in base.py)
        keyframes = []
        for idx, fp in enumerate(frame_files):
            ts_ms = self._estimate_timestamp_ms(fp.stem, idx)
            keyframes.append({
                "index": idx,
                "timestamp_ms": ts_ms,
                "path": fp.name,
            })

        ctx.keyframes = keyframes
        logger.info("Extracted %d keyframes for task %s", len(keyframes), task_id)

        # Persist keyframes.json
        dest = self._persistence.task_dir(task_id) / "keyframes.json"
        dest.write_text(
            json.dumps(keyframes, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        return ctx

    def _extract_interval(self, video_path: Path, frames_dir: Path) -> None:
        """Fixed-interval keyframe extraction."""
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-vf", f"fps=1/{self._interval_s}",
            "-q:v", str(self._quality),
            str(frames_dir / f"%04d.{self._fmt}"),
        ]
        self._run_ffmpeg(cmd)

    def _extract_scene(self, video_path: Path, frames_dir: Path) -> None:
        """Scene-change-based keyframe extraction."""
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-vf", f"select='gt(scene,{self._scene_threshold})'",
            "-vsync", "vfn",
            "-q:v", str(self._quality),
            str(frames_dir / f"%04d.{self._fmt}"),
        ]
        self._run_ffmpeg(cmd)

    @staticmethod
    def _run_ffmpeg(cmd: list[str]) -> None:
        """Run ffmpeg subprocess, raise on failure."""
        try:
            logger.info("Running: %s", " ".join(cmd))
            result = subprocess.run(cmd, capture_output=True)
            if result.returncode != 0:
                stderr = result.stderr.decode(errors="replace")
                raise RuntimeError(
                    f"ffmpeg keyframe extraction failed (code {result.returncode}): {stderr}"
                )
        except FileNotFoundError:
            raise RuntimeError(
                "ffmpeg not found. Please install ffmpeg and ensure it is on PATH."
            )

    def _estimate_timestamp_ms(self, stem: str, index: int) -> int:
        """Estimate frame timestamp from filename or index.

        ffmpeg interval mode names files 0001, 0002, ...
        Each corresponds to index * interval seconds.
        """
        match = re.match(r"^(\d+)$", stem)
        if match and self._strategy == "interval":
            # ffmpeg numbering starts at 1
            frame_num = int(match.group(1)) - 1
            return int(frame_num * self._interval_s * 1000)
        # Fallback: use index
        return int(index * self._interval_s * 1000)
