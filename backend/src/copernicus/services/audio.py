from pathlib import Path

from copernicus.exceptions import AudioProcessingError
from copernicus.utils.ffmpeg import run as ffmpeg_run

# 会议场景优化滤镜链：
# highpass=f=200 — 过滤低频噪声（空调、风扇）
# afftdn=nf=-25 — FFT 降噪，去除稳态背景噪声
# dynaudnorm p=0.9:m=10:s=3 — 动态音量标准化，s=3 平滑说话人切换
_ENHANCE_FILTER = "highpass=f=200,afftdn=nf=-25,dynaudnorm=p=0.9:m=10:s=3"

_FFMPEG_TIMEOUT_S = 600


class AudioService:
    """音视频 → 16kHz 单声道 WAV。音频文件与视频音轨共用同一条转换命令。"""

    def __init__(self, audio_enhance: bool = True) -> None:
        self._audio_enhance = audio_enhance

    async def extract_wav(self, input_path: Path, output_path: Path) -> Path:
        """把 input_path（音频或视频）转成 16kHz 单声道 WAV 写入 output_path。"""
        cmd = ["ffmpeg", "-y", "-i", str(input_path)]
        if self._audio_enhance:
            cmd += ["-af", _ENHANCE_FILTER]
        cmd += ["-ar", "16000", "-ac", "1", "-acodec", "pcm_s16le", "-f", "wav", str(output_path)]

        rc, stderr = await ffmpeg_run(cmd, timeout=_FFMPEG_TIMEOUT_S)
        if rc != 0:
            output_path.unlink(missing_ok=True)
            raise AudioProcessingError(f"ffmpeg failed (code {rc}): {stderr}")
        return output_path

    @staticmethod
    def cleanup(path: Path) -> None:
        """处理完成后删除临时音频文件。"""
        path.unlink(missing_ok=True)
