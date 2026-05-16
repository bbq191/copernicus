import uuid
from pathlib import Path

from copernicus.config import Settings
from copernicus.exceptions import AudioProcessingError
from copernicus.utils.ffmpeg import run as ffmpeg_run


class AudioService:
    def __init__(self, settings: Settings) -> None:
        self._upload_dir = settings.upload_dir
        self._audio_enhance = settings.audio_enhance

    async def preprocess(self, audio_bytes: bytes, original_filename: str) -> Path:
        """将上传的音频通过 ffmpeg 转换为 16kHz 单声道 WAV 格式。"""
        self._upload_dir.mkdir(parents=True, exist_ok=True)

        suffix = Path(original_filename).suffix or ".bin"
        file_id = uuid.uuid4().hex
        input_path = self._upload_dir / f"{file_id}{suffix}"
        output_path = self._upload_dir / f"{file_id}_processed.wav"

        input_path.write_bytes(audio_bytes)

        try:
            await self._run_ffmpeg(input_path, output_path, self._audio_enhance)
        finally:
            input_path.unlink(missing_ok=True)

        return output_path

    @staticmethod
    async def _run_ffmpeg(
        input_path: Path, output_path: Path, audio_enhance: bool = True
    ) -> None:
        if audio_enhance:
            # 会议场景优化滤镜链：
            # highpass=f=200 — 过滤低频噪声（空调、风扇）
            # afftdn=nf=-25 — FFT 降噪，去除稳态背景噪声
            # dynaudnorm p=0.9:m=10:s=3 — 动态音量标准化，s=3 平滑说话人切换
            cmd = [
                "ffmpeg", "-y",
                "-i", str(input_path),
                "-af", "highpass=f=200,afftdn=nf=-25,dynaudnorm=p=0.9:m=10:s=3",
                "-ar", "16000", "-ac", "1",
                "-acodec", "pcm_s16le", "-f", "wav",
                str(output_path),
            ]
        else:
            cmd = [
                "ffmpeg", "-y",
                "-i", str(input_path),
                "-ar", "16000", "-ac", "1",
                "-acodec", "pcm_s16le", "-f", "wav",
                str(output_path),
            ]
        rc, stderr = await ffmpeg_run(cmd, timeout=600)
        if rc != 0:
            raise AudioProcessingError(f"ffmpeg failed (code {rc}): {stderr}")

    @staticmethod
    def cleanup(path: Path) -> None:
        """处理完成后删除临时音频文件。"""
        path.unlink(missing_ok=True)
