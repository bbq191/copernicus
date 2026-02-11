"""Pipeline service facade.

Transcript processing mode delegates to a Stage-based orchestrator.

Author: afu
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from copernicus.services.asr import ASRService
from copernicus.services.audio import AudioService
from copernicus.services.corrector import CorrectorService
from copernicus.services.hotword_replacer import HotwordReplacerService
from copernicus.services.pipeline.base import (
    PipelineContext,
    TranscriptEntry,
    TranscriptResult,
)
from copernicus.services.pipeline.orchestrator import PipelineOrchestrator
from copernicus.services.pipeline.stages import (
    ASRTranscribeStage,
    AudioPreprocessStage,
    FaceDetectStage,
    KeyframeExtractStage,
    OCRScanStage,
    SpeakerSmoothStage,
    TextCorrectionStage,
    TranscriptBuildStage,
    VideoPreprocessStage,
)
from copernicus.utils.types import ProgressCallback

if TYPE_CHECKING:
    from copernicus.config import Settings
    from copernicus.services.face_detector import FaceDetectorService
    from copernicus.services.ocr import OCRService
    from copernicus.services.persistence import PersistenceService

logger = logging.getLogger(__name__)

# Re-export data classes for backward compatibility
__all__ = [
    "PipelineService",
    "TranscriptEntry",
    "TranscriptResult",
]


class PipelineService:
    """Facade: transcript pipeline uses Stage orchestrator."""

    def __init__(
        self,
        audio_service: AudioService,
        asr_service: ASRService,
        corrector_service: CorrectorService,
        confidence_threshold: float = 0.95,
        chunk_size: int = 800,
        run_merge_gap: int = 3,
        pre_merge_gap_ms: int = 1000,
        hotword_replacer: HotwordReplacerService | None = None,
        settings: Settings | None = None,
        persistence: PersistenceService | None = None,
        ocr_service: OCRService | None = None,
        face_detector: FaceDetectorService | None = None,
    ) -> None:
        self._asr = asr_service
        self._corrector = corrector_service
        self._hotword_replacer = hotword_replacer

        asr_stage = ASRTranscribeStage(asr_service, audio_service, asyncio.Lock())

        # Transcript pipeline (7 stages, video-related ones skip for audio)
        self._transcript_pipeline = PipelineOrchestrator()

        # 1. Video -> extract audio (skipped for audio files)
        if settings and persistence:
            self._transcript_pipeline.register(VideoPreprocessStage(settings, persistence))

        # 2. Audio -> WAV 16kHz (skipped when VideoPreprocess already set wav_path)
        self._transcript_pipeline.register(AudioPreprocessStage(audio_service))

        # 3. ASR
        self._transcript_pipeline.register(asr_stage)

        # 4. Video -> keyframe extraction (skipped for audio files)
        if settings and persistence:
            self._transcript_pipeline.register(
                KeyframeExtractStage(settings, persistence)
            )

        # 5. OCR scan keyframes (skipped for audio files)
        if ocr_service and persistence:
            self._transcript_pipeline.register(
                OCRScanStage(ocr_service, persistence, enabled=settings.ocr_enabled if settings else True)
            )

        # 6. Face detection on keyframes (skipped for audio files)
        if face_detector and persistence and settings:
            interval_ms = int(settings.keyframe_interval_s * 1000)
            self._transcript_pipeline.register(
                FaceDetectStage(
                    face_detector, persistence,
                    enabled=settings.face_detect_enabled,
                    interval_ms=interval_ms,
                )
            )

        # 7-9. Text processing
        self._transcript_pipeline.register(SpeakerSmoothStage(pre_merge_gap_ms))
        self._transcript_pipeline.register(
            TextCorrectionStage(corrector_service, confidence_threshold)
        )
        self._transcript_pipeline.register(TranscriptBuildStage())

    def _merge_hotwords(self, request_hotwords: list[str] | None) -> list[str] | None:
        """Combine global hotwords (from HotwordReplacerService) with per-request hotwords."""
        global_hw = (
            self._hotword_replacer.get_asr_hotwords() if self._hotword_replacer else []
        )
        combined = list(global_hw)
        if request_hotwords:
            combined.extend(request_hotwords)
        return combined if combined else None

    async def process_transcript(
        self,
        audio_bytes: bytes,
        filename: str,
        hotwords: list[str] | None = None,
        on_progress: ProgressCallback | None = None,
        task_id: str = "",
    ) -> TranscriptResult:
        """Run transcript pipeline via Stage orchestrator."""
        logger.info("Pipeline process_transcript started for: %s", filename)
        start = time.perf_counter()

        ctx = PipelineContext(
            task_id=task_id,
            audio_bytes=audio_bytes,
            filename=filename,
            hotwords=self._merge_hotwords(hotwords),
            sentence_timestamp=True,
        )

        def _stage_progress(
            stage_name: str,
            stage_idx: int,
            total_stages: int,
            current: int,
            total: int,
        ) -> None:
            if on_progress and stage_name == "text_correction":
                on_progress(current, total)

        ctx = await self._transcript_pipeline.run(ctx, on_stage_progress=_stage_progress)

        elapsed_ms = (time.perf_counter() - start) * 1000
        return TranscriptResult(
            transcript=ctx.transcript_entries,
            processing_time_ms=round(elapsed_ms, 2),
        )
