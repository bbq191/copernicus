import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path

from copernicus.services.asr import ASRResult, Segment
from copernicus.services.audio import AudioService
from copernicus.services.asr import ASRService
from copernicus.services.corrector import CorrectorService, ProgressCallback


@dataclass
class TranscriptionResult:
    raw_text: str
    corrected_text: str
    segments: list[Segment] = field(default_factory=list)
    processing_time_ms: float = 0.0


class PipelineService:
    def __init__(
        self,
        audio_service: AudioService,
        asr_service: ASRService,
        corrector_service: CorrectorService,
    ) -> None:
        self._audio = audio_service
        self._asr = asr_service
        self._corrector = corrector_service

    async def process(
        self,
        audio_bytes: bytes,
        filename: str,
        hotwords: list[str] | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> TranscriptionResult:
        """Run the full pipeline: preprocess -> ASR -> LLM correction."""
        start = time.perf_counter()

        # 1. Audio preprocessing (async ffmpeg)
        wav_path: Path = await self._audio.preprocess(audio_bytes, filename)

        try:
            # 2. ASR inference (sync, run in thread)
            asr_result: ASRResult = await asyncio.to_thread(
                self._asr.transcribe, wav_path, hotwords
            )

            # 3. LLM correction (async)
            corrected_text = await self._corrector.correct(
                asr_result.text, on_progress=on_progress
            )
        finally:
            # 4. Cleanup temp file
            self._audio.cleanup(wav_path)

        elapsed_ms = (time.perf_counter() - start) * 1000

        return TranscriptionResult(
            raw_text=asr_result.text,
            corrected_text=corrected_text,
            segments=asr_result.segments,
            processing_time_ms=round(elapsed_ms, 2),
        )

    async def process_raw(
        self,
        audio_bytes: bytes,
        filename: str,
        hotwords: list[str] | None = None,
    ) -> TranscriptionResult:
        """Run ASR only, without LLM correction."""
        start = time.perf_counter()

        wav_path: Path = await self._audio.preprocess(audio_bytes, filename)

        try:
            asr_result: ASRResult = await asyncio.to_thread(
                self._asr.transcribe, wav_path, hotwords
            )
        finally:
            self._audio.cleanup(wav_path)

        elapsed_ms = (time.perf_counter() - start) * 1000

        return TranscriptionResult(
            raw_text=asr_result.text,
            corrected_text=asr_result.text,
            segments=asr_result.segments,
            processing_time_ms=round(elapsed_ms, 2),
        )
