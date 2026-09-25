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


def _no_probe():
    async def probe(_path):
        return None

    return patch("copernicus.services.pipeline.stages.keyframe_extract.probe_duration_s", probe)


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

        with patch("copernicus.services.pipeline.stages.keyframe_extract.ffmpeg_run", fake), _no_probe():
            result = asyncio.run(stage.execute(ctx))

        assert [k["timestamp_ms"] for k in result.keyframes] == [0, 10000, 20000]


class TestIntervalCap:
    """长视频拉宽抽帧间隔，而不是先全抽再删。"""

    def _run(self, tmp_path, duration_s):
        stage, _ = _stage(tmp_path, "interval")  # 间隔 10s，上限 100 帧
        commands: list[list[str]] = []

        async def ffmpeg(cmd, timeout=600):
            commands.append(cmd)
            for i in range(1, 4):
                (tmp_path / "frames" / f"{i:04d}.jpg").write_bytes(b"jpg")
            return 0, ""

        async def probe(_path):
            return duration_s

        base = "copernicus.services.pipeline.stages.keyframe_extract"
        with patch(f"{base}.ffmpeg_run", ffmpeg), patch(f"{base}.probe_duration_s", probe):
            result = asyncio.run(stage.execute(_ctx(tmp_path)))
        return commands[0], result

    def test_long_video_widens_the_interval_to_stay_under_the_cap(self, tmp_path):
        cmd, result = self._run(tmp_path, duration_s=5000)  # 5000/100 = 50s
        assert "fps=1/50.0" in cmd
        assert [k["timestamp_ms"] for k in result.keyframes] == [0, 50000, 100000]

    def test_short_video_keeps_the_configured_interval(self, tmp_path):
        cmd, _ = self._run(tmp_path, duration_s=300)
        assert "fps=1/10" in cmd or "fps=1/10.0" in cmd

    def test_unknown_duration_falls_back_to_the_configured_interval(self, tmp_path):
        cmd, _ = self._run(tmp_path, duration_s=None)
        assert "fps=1/10" in cmd or "fps=1/10.0" in cmd
