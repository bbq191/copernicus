"""Pipeline 服务外观类。

转写处理模式委托给基于 Stage 的编排器执行。

作者：afu
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
from copernicus.utils.types import ProgressCallback, StageChangeCallback

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
    """外观类：转写 Pipeline 基于 Stage 编排器实现。"""

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

        # Transcript pipeline -- stage order matters for status progression:
        #   video_preprocess → keyframe_extract → ocr_scan → face_detect
        #   → audio_preprocess → asr_transcribe → speaker_smooth
        #   → text_correction → transcript_build
        #
        # Visual stages run before ASR so status advances linearly:
        #   EXTRACTING_FRAMES → SCANNING_VISUAL → PROCESSING_ASR → CORRECTING
        self._transcript_pipeline = PipelineOrchestrator()

        # 1. Video -> extract audio + set video_path (skipped for audio files)
        if settings and persistence:
            self._transcript_pipeline.register(VideoPreprocessStage(settings, persistence))

        # 2. Video -> keyframe extraction (skipped for audio files)
        if settings and persistence:
            self._transcript_pipeline.register(
                KeyframeExtractStage(settings, persistence)
            )

        # 3. OCR scan keyframes (skipped for audio files)
        if ocr_service and persistence:
            self._transcript_pipeline.register(
                OCRScanStage(ocr_service, persistence, enabled=settings.ocr_enabled if settings else True)
            )

        # 4. Face detection on keyframes (skipped for audio files)
        if face_detector and persistence and settings:
            interval_ms = int(settings.keyframe_interval_s * 1000)
            self._transcript_pipeline.register(
                FaceDetectStage(
                    face_detector, persistence,
                    enabled=settings.face_detect_enabled,
                    interval_ms=interval_ms,
                )
            )

        # 5. Audio -> WAV 16kHz (skipped when VideoPreprocess already set wav_path)
        self._transcript_pipeline.register(AudioPreprocessStage(audio_service))

        # 6. ASR
        self._transcript_pipeline.register(asr_stage)

        # 7-9. Text processing
        self._transcript_pipeline.register(SpeakerSmoothStage(pre_merge_gap_ms))
        self._transcript_pipeline.register(
            TextCorrectionStage(corrector_service, confidence_threshold)
        )
        self._transcript_pipeline.register(TranscriptBuildStage())

    def _merge_hotwords(self, request_hotwords: list[str] | None) -> list[str] | None:
        """合并全局热词（来自 HotwordReplacerService）与请求级热词。"""
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
        on_stage_change: StageChangeCallback | None = None,
        task_id: str = "",
        visual_scan: bool = False,
    ) -> TranscriptResult:
        """通过 Stage 编排器运行转写 Pipeline。"""
        logger.info(
            "Pipeline process_transcript started for: %s (visual_scan=%s)",
            filename, visual_scan,
        )
        start = time.perf_counter()

        ctx = PipelineContext(
            task_id=task_id,
            audio_bytes=audio_bytes,
            filename=filename,
            hotwords=self._merge_hotwords(hotwords),
            sentence_timestamp=True,
            visual_scan=visual_scan,
        )

        _last_stage: list[str] = [""]

        def _stage_progress(
            stage_name: str,
            stage_idx: int,
            total_stages: int,
            current: int,
            total: int,
        ) -> None:
            # 每个 Stage 首次触发时通知外部状态切换
            if on_stage_change and stage_name != _last_stage[0]:
                _last_stage[0] = stage_name
                on_stage_change(stage_name)

            if on_progress:
                if stage_name == "text_correction":
                    on_progress(current, total)
                elif stage_name in ("ocr_scan", "face_detect"):
                    on_progress(current, total)

        ctx = await self._transcript_pipeline.run(ctx, on_stage_progress=_stage_progress)

        elapsed_ms = (time.perf_counter() - start) * 1000
        return TranscriptResult(
            transcript=ctx.transcript_entries,
            processing_time_ms=round(elapsed_ms, 2),
        )
