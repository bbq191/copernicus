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

# ffmpeg showinfo 过滤器为每个输出帧打印一行，其中 pts_time 是该帧在视频中的真实时间（秒）
_SHOWINFO_PTS_TIME = re.compile(r"Parsed_showinfo.*?pts_time:\s*([0-9.]+)")


def parse_showinfo_timestamps_ms(stderr: str) -> list[int]:
    """从 ffmpeg stderr 中按输出顺序提取各帧的真实时间戳（毫秒）。"""
    return [int(float(t) * 1000) for t in _SHOWINFO_PTS_TIME.findall(stderr)]


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

        # 帧编号（文件名，从 1 起）→ 视频内真实时间戳
        if self._strategy == "scene":
            timestamps = await self._extract_scene(ctx.video_path, frames_dir)
        else:
            timestamps = await self._extract_interval(ctx.video_path, frames_dir)

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
                "timestamp_ms": timestamps.get(int(fp.stem), int(idx * self._interval_s * 1000)),
                "path": fp.name,
            }
            for idx, fp in enumerate(frame_files)
        ]

        ctx.keyframes = keyframes
        logger.info("Extracted %d keyframes for task %s", len(keyframes), ctx.task_id)

        dest = self._persistence.task_dir(ctx.task_id) / "keyframes.json"
        dest.write_text(json.dumps(keyframes, ensure_ascii=False, indent=2), encoding="utf-8")

        return ctx

    async def _extract_interval(self, video_path: Path, frames_dir: Path) -> dict[int, int]:
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-vf", f"fps=1/{self._interval_s}",
            "-q:v", str(self._quality),
            str(frames_dir / f"%04d.{self._fmt}"),
        ]
        await self._run_ffmpeg(cmd)
        # 等间隔抽帧：第 n 帧位于 (n-1) * 间隔
        count = len(list(frames_dir.glob(f"*.{self._fmt}")))
        return {n: int((n - 1) * self._interval_s * 1000) for n in range(1, count + 1)}

    async def _extract_scene(self, video_path: Path, frames_dir: Path) -> dict[int, int]:
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-vf", f"select='gt(scene,{self._scene_threshold})',showinfo",
            "-vsync", "vfr",
            "-q:v", str(self._quality),
            str(frames_dir / f"%04d.{self._fmt}"),
        ]
        stderr = await self._run_ffmpeg(cmd)
        # 场景切换的时刻不等距，必须使用 ffmpeg 报告的真实时间戳
        return {n: ms for n, ms in enumerate(parse_showinfo_timestamps_ms(stderr), start=1)}

    @staticmethod
    async def _run_ffmpeg(cmd: list[str]) -> str:
        logger.info("Running: %s", " ".join(cmd))
        rc, stderr = await ffmpeg_run(cmd, timeout=600)
        if rc != 0:
            raise RuntimeError(f"ffmpeg keyframe extraction failed (code {rc}): {stderr}")
        return stderr
