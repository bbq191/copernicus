import asyncio
import subprocess
import uuid
from pathlib import Path

from copernicus.config import Settings
from copernicus.exceptions import AudioProcessingError


class AudioService:
    def __init__(self, settings: Settings) -> None:
        self._upload_dir = settings.upload_dir
        self._audio_enhance = settings.audio_enhance

    async def preprocess(self, audio_bytes: bytes, original_filename: str) -> Path:
        """Convert uploaded audio to 16kHz mono WAV via ffmpeg."""
        self._upload_dir.mkdir(parents=True, exist_ok=True)

        suffix = Path(original_filename).suffix or ".bin"
        file_id = uuid.uuid4().hex
        input_path = self._upload_dir / f"{file_id}{suffix}"
        # 使用不同的文件名避免输入输出相同（ffmpeg 无法原地编辑）
        output_path = self._upload_dir / f"{file_id}_processed.wav"

        input_path.write_bytes(audio_bytes)

        try:
            await asyncio.to_thread(
                self._run_ffmpeg, input_path, output_path, self._audio_enhance
            )
        finally:
            input_path.unlink(missing_ok=True)

        return output_path

    @staticmethod
    def _run_ffmpeg(
        input_path: Path, output_path: Path, audio_enhance: bool = True
    ) -> None:
        """Run ffmpeg synchronously (called via asyncio.to_thread).

        Args:
            audio_enhance: 启用音频增强滤镜（会议场景优化）

        滤镜链说明（针对会议场景）：
        1. highpass=f=200 - 过滤低频噪声（空调、电脑风扇、交通噪音）
        2. afftdn=nf=-25 - FFT 降噪，去除稳态背景噪声
        3. dynaudnorm - 动态音量标准化，解决说话人远近不一的问题
           - p=0.9 峰值目标 90%（留余量避免削波）
           - m=10 最大增益 10dB（避免过度放大噪声）
           - s=3 平滑窗口 3 秒（适应说话人切换）
        """
        import logging
        logger = logging.getLogger(__name__)

        try:
            if audio_enhance:
                # 会议场景优化滤镜链
                # 增加 s=3 平滑窗口，更好地适应说话人切换
                # 明确指定 pcm_s16le 编码，确保 soundfile 正确解析
                cmd = [
                    "ffmpeg", "-y",
                    "-i", str(input_path),
                    "-af", "highpass=f=200,afftdn=nf=-25,dynaudnorm=p=0.9:m=10:s=3",
                    "-ar", "16000",
                    "-ac", "1",
                    "-acodec", "pcm_s16le",
                    "-f", "wav",
                    str(output_path),
                ]
            else:
                # 仅格式转换
                # 明确指定 pcm_s16le 编码，确保 soundfile 正确解析
                cmd = [
                    "ffmpeg", "-y",
                    "-i", str(input_path),
                    "-ar", "16000",
                    "-ac", "1",
                    "-acodec", "pcm_s16le",
                    "-f", "wav",
                    str(output_path),
                ]

            logger.info("Running ffmpeg with audio_enhance=%s", audio_enhance)
            result = subprocess.run(cmd, capture_output=True)
            if result.returncode != 0:
                raise AudioProcessingError(
                    f"ffmpeg failed (code {result.returncode}): {result.stderr.decode()}"
                )
            logger.info("ffmpeg completed successfully")
        except FileNotFoundError:
            raise AudioProcessingError(
                "ffmpeg not found. Please install ffmpeg and ensure it is on PATH."
            )

    @staticmethod
    def cleanup(path: Path) -> None:
        """Remove temporary audio file after processing."""
        path.unlink(missing_ok=True)
