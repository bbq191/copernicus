"""音视频预处理阶段：用真实 ffmpeg 生成的小文件验证（无 ffmpeg 时跳过）。"""

import shutil
import subprocess
import wave

import pytest

from copernicus.config import Settings
from copernicus.exceptions import AudioProcessingError
from copernicus.services.audio import AudioService
from copernicus.services.persistence import PersistenceService
from copernicus.services.pipeline.base import PipelineContext
from copernicus.services.pipeline.stages import AudioPreprocessStage, VideoPreprocessStage

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="需要 ffmpeg")

TID = "a" * 32


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


@pytest.fixture
def persistence(tmp_path) -> PersistenceService:
    return PersistenceService(tmp_path / "uploads")


def _assert_16k_mono(path) -> None:
    with wave.open(str(path)) as w:
        assert (w.getframerate(), w.getnchannels()) == (16000, 1)
        assert w.getnframes() > 0


class TestAudioPreprocess:
    async def test_converts_any_input_to_16k_mono_wav_inside_the_task_dir(self, tmp_path, persistence):
        source = tmp_path / "in.mp3"
        _ffmpeg("-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-ar", "44100", "-ac", "2", str(source))
        stage = AudioPreprocessStage(AudioService(audio_enhance=True), persistence)
        ctx = PipelineContext(task_id=TID, media_path=source, filename="in.mp3")

        assert stage.should_run(ctx)
        ctx = await stage.execute(ctx)

        assert ctx.wav_path == persistence.path_of(TID) / "processed.wav"
        _assert_16k_mono(ctx.wav_path)

    async def test_conversion_failure_raises_and_leaves_no_partial_output(self, tmp_path, persistence):
        bogus = tmp_path / "not-audio.wav"
        bogus.write_bytes(b"this is not media")
        stage = AudioPreprocessStage(AudioService(), persistence)
        ctx = PipelineContext(task_id=TID, media_path=bogus, filename="not-audio.wav")

        with pytest.raises(AudioProcessingError):
            await stage.execute(ctx)
        assert not (persistence.path_of(TID) / "processed.wav").exists()

    async def test_plain_conversion_without_enhancement(self, tmp_path, persistence):
        source = tmp_path / "in.wav"
        _ffmpeg("-f", "lavfi", "-i", "sine=frequency=300:duration=1", str(source))
        stage = AudioPreprocessStage(AudioService(audio_enhance=False), persistence)
        ctx = await stage.execute(PipelineContext(task_id=TID, media_path=source, filename="in.wav"))
        _assert_16k_mono(ctx.wav_path)


class TestVideoPreprocess:
    async def test_extracts_the_audio_track_and_marks_the_context_as_video(self, tmp_path, persistence):
        source = tmp_path / "video.mp4"
        _ffmpeg(
            "-f", "lavfi", "-i", "testsrc=duration=1:size=64x64:rate=5",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-shortest", str(source),
        )
        stage = VideoPreprocessStage(Settings(), persistence, AudioService())
        ctx = PipelineContext(task_id=TID, media_path=source, filename="video.mp4")

        assert stage.should_run(ctx)
        ctx = await stage.execute(ctx)

        assert ctx.media_type == "video" and ctx.video_path == source
        assert ctx.wav_path == persistence.path_of(TID) / "extracted.wav"
        _assert_16k_mono(ctx.wav_path)

    def test_audio_files_are_skipped_by_extension(self, persistence):
        stage = VideoPreprocessStage(Settings(), persistence, AudioService())
        assert not stage.should_run(PipelineContext(filename="a.wav"))
        assert not stage.should_run(PipelineContext(filename=""))
