import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch


from copernicus.config import Settings
from copernicus.services.pipeline.base import PipelineContext
from copernicus.services.pipeline.stages.keyframe_extract import (
    KeyframeExtractStage,
    parse_showinfo_timestamps_ms,
)

_SHOWINFO = """\
[Parsed_showinfo_1 @ 0x55d] n:   0 pts:  75000 pts_time:12.5    duration: 1
[Parsed_showinfo_1 @ 0x55d] n:   1 pts: 300300 pts_time:47.334  duration: 1
[Parsed_showinfo_1 @ 0x55d] n:   2 pts: 900000 pts_time:100     duration: 1
frame=    3 fps=0.0 q=24.8 size=N/A
"""


class TestParseShowinfo:
    def test_extracts_real_timestamps_in_order(self):
        assert parse_showinfo_timestamps_ms(_SHOWINFO) == [12500, 47334, 100000]

    def test_no_matches(self):
        assert parse_showinfo_timestamps_ms("ffmpeg version 6.0") == []


def _stage(tmp_path, strategy: str) -> tuple[KeyframeExtractStage, MagicMock]:
    settings = Settings(keyframe_strategy=strategy, keyframe_interval_s=10, keyframe_max_count=100)
    persistence = MagicMock()
    frames = tmp_path / "frames"
    frames.mkdir()
    persistence.frames_dir.return_value = frames
    persistence.task_dir.return_value = tmp_path
    return KeyframeExtractStage(settings, persistence), persistence


def _ctx(tmp_path) -> PipelineContext:
    ctx = PipelineContext(filename="v.mp4")
    ctx.visual_scan = True
    ctx.video_path = tmp_path / "v.mp4"
    ctx.task_id = "a" * 32
    return ctx


def _fake_ffmpeg(frames_dir: Path, count: int, stderr: str):
    async def run(cmd, timeout=600):
        for i in range(1, count + 1):
            (frames_dir / f"{i:04d}.jpg").write_bytes(b"jpg")
        return 0, stderr

    return run


class TestTimestamps:
    def test_scene_mode_uses_real_scene_times_not_index_times(self, tmp_path):
        stage, _ = _stage(tmp_path, "scene")
        ctx = _ctx(tmp_path)
        fake = _fake_ffmpeg(tmp_path / "frames", 3, _SHOWINFO)

        with patch("copernicus.services.pipeline.stages.keyframe_extract.ffmpeg_run", fake):
            result = asyncio.run(stage.execute(ctx))

        assert [k["timestamp_ms"] for k in result.keyframes] == [12500, 47334, 100000]

    def test_interval_mode_positions_frames_by_interval(self, tmp_path):
        stage, _ = _stage(tmp_path, "interval")
        ctx = _ctx(tmp_path)
        fake = _fake_ffmpeg(tmp_path / "frames", 3, "")

        with patch("copernicus.services.pipeline.stages.keyframe_extract.ffmpeg_run", fake):
            result = asyncio.run(stage.execute(ctx))

        assert [k["timestamp_ms"] for k in result.keyframes] == [0, 10000, 20000]
