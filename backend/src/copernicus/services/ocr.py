"""OCR service using RapidOCR (ONNX, CPU-only).

Author: afu
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from copernicus.schemas.visual import OCRRecord

if TYPE_CHECKING:
    from copernicus.config import Settings

logger = logging.getLogger(__name__)


class OCRService:
    """Lazy-loaded RapidOCR wrapper for scanning keyframes."""

    def __init__(self, settings: Settings) -> None:
        self._confidence_threshold = settings.ocr_confidence_threshold
        self._min_text_length = settings.ocr_min_text_length
        self._engine = None

    def _ensure_engine(self) -> None:
        if self._engine is not None:
            return
        from rapidocr import RapidOCR

        self._engine = RapidOCR()
        logger.info("RapidOCR engine initialized (CPU)")

    def scan_frame(self, image_path: str, timestamp_ms: int) -> list[OCRRecord]:
        """Run OCR on a single keyframe image. Synchronous -- call via to_thread."""
        self._ensure_engine()
        assert self._engine is not None

        result = self._engine(image_path)
        if result is None or result.txts is None:
            return []

        records: list[OCRRecord] = []
        for i, txt in enumerate(result.txts):
            score = result.scores[i] if result.scores else 0.0
            if score < self._confidence_threshold:
                continue
            if len(txt) < self._min_text_length:
                continue
            bbox = result.boxes[i].tolist() if result.boxes is not None else []
            records.append(
                OCRRecord(
                    timestamp_ms=timestamp_ms,
                    text=txt,
                    confidence=round(score, 4),
                    frame_path=image_path,
                    bbox=bbox,
                )
            )
        return records
