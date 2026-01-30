import asyncio
import subprocess
import uuid
from pathlib import Path

from copernicus.config import Settings
from copernicus.exceptions import AudioProcessingError


class AudioService:
    def __init__(self, settings: Settings) -> None:
        self._upload_dir = settings.upload_dir

    async def preprocess(self, audio_bytes: bytes, original_filename: str) -> Path:
        """Convert uploaded audio to 16kHz mono WAV via ffmpeg."""
        self._upload_dir.mkdir(parents=True, exist_ok=True)

        suffix = Path(original_filename).suffix or ".bin"
        input_path = self._upload_dir / f"{uuid.uuid4().hex}{suffix}"
        output_path = input_path.with_suffix(".wav")

        input_path.write_bytes(audio_bytes)

        try:
            await asyncio.to_thread(
                self._run_ffmpeg, input_path, output_path
            )
        finally:
            input_path.unlink(missing_ok=True)

        return output_path

    @staticmethod
    def _run_ffmpeg(input_path: Path, output_path: Path) -> None:
        """Run ffmpeg synchronously (called via asyncio.to_thread)."""
        try:
            result = subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-i", str(input_path),
                    "-ar", "16000",
                    "-ac", "1",
                    "-f", "wav",
                    str(output_path),
                ],
                capture_output=True,
            )
            if result.returncode != 0:
                raise AudioProcessingError(
                    f"ffmpeg failed (code {result.returncode}): {result.stderr.decode()}"
                )
        except FileNotFoundError:
            raise AudioProcessingError(
                "ffmpeg not found. Please install ffmpeg and ensure it is on PATH."
            )

    @staticmethod
    def cleanup(path: Path) -> None:
        """Remove temporary audio file after processing."""
        path.unlink(missing_ok=True)
