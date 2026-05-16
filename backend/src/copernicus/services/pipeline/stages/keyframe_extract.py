"""Stage: Keyframe extraction from video."""

import json
import logging
import re
from pathlib import Path

from copernicus.config import Settings
from copernicus.services.persistence import PersistenceService
from copernicus.services.pipeline.base import PipelineContext
from copernicus.utils.ffmpeg import run as ffmpeg_run
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
        return ctx.visual_scan and ctx.video_path is not None

    async def execute(
        self,
        ctx: PipelineContext,
        on_progress: ProgressCallback | None = None,
    ) -> PipelineContext:
        if ctx.video_path is None:
            raise RuntimeError("video_path is None in KeyframeExtractStage")
        if not ctx.task_id:
            raise RuntimeError("task_id is empty in KeyframeExtractStage")

        frames_dir = self._persistence.frames_dir(ctx.task_id)

        if self._strategy == "scene":
            await self._extract_scene(ctx.video_path, frames_dir)
        else:
            await self._extract_interval(ctx.video_path, frames_dir)

        frame_files = sorted(frames_dir.glob(f"*.{self._fmt}"))

        if len(frame_files) > self._max_count:
            step = len(frame_files) / self._max_count
            sampled = {frame_files[int(i * step)] for i in range(self._max_count)}
            for f in frame_files:
                if f not in sampled:
                    f.unlink(missing_ok=True)
            frame_files = sorted(sampled)

        keyframes = [
            {
                "index": idx,
                "timestamp_ms": self._estimate_timestamp_ms(fp.stem, idx),
                "path": fp.name,
            }
            for idx, fp in enumerate(frame_files)
        ]

        ctx.keyframes = keyframes
        logger.info("Extracted %d keyframes for task %s", len(keyframes), ctx.task_id)

        dest = self._persistence.task_dir(ctx.task_id) / "keyframes.json"
        dest.write_text(json.dumps(keyframes, ensure_ascii=False, indent=2), encoding="utf-8")

        return ctx

    async def _extract_interval(self, video_path: Path, frames_dir: Path) -> None:
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-vf", f"fps=1/{self._interval_s}",
            "-q:v", str(self._quality),
            str(frames_dir / f"%04d.{self._fmt}"),
        ]
        await self._run_ffmpeg(cmd)

    async def _extract_scene(self, video_path: Path, frames_dir: Path) -> None:
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-vf", f"select='gt(scene,{self._scene_threshold})'",
            "-vsync", "vfn",
            "-q:v", str(self._quality),
            str(frames_dir / f"%04d.{self._fmt}"),
        ]
        await self._run_ffmpeg(cmd)

    @staticmethod
    async def _run_ffmpeg(cmd: list[str]) -> None:
        logger.info("Running: %s", " ".join(cmd))
        rc, stderr = await ffmpeg_run(cmd, timeout=600)
        if rc != 0:
            raise RuntimeError(f"ffmpeg keyframe extraction failed (code {rc}): {stderr}")

    def _estimate_timestamp_ms(self, stem: str, index: int) -> int:
        match = re.match(r"^(\d+)$", stem)
        if match and self._strategy == "interval":
            return int((int(match.group(1)) - 1) * self._interval_s * 1000)
        return int(index * self._interval_s * 1000)
