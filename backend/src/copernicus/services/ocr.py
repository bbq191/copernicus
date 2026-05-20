"""基于 RapidOCR（ONNX，仅 CPU）的 OCR 服务。

作者：afu
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from copernicus.schemas.visual import OCRRecord

if TYPE_CHECKING:
    from copernicus.config import Settings

logger = logging.getLogger(__name__)


class OCRService:
    """懒加载 RapidOCR 封装，用于扫描关键帧图像。"""

    def __init__(self, settings: Settings) -> None:
        self._confidence_threshold = settings.ocr_confidence_threshold
        self._min_text_length = settings.ocr_min_text_length
        self._engine = None

    def _ensure_engine(self) -> None:
        if self._engine is not None:
            return
        from rapidocr import RapidOCR

        self._engine = RapidOCR()
        # "text detection result is empty" fires for every blank frame — suppress noise
        logging.getLogger("RapidOCR").setLevel(logging.ERROR)
        logger.info("RapidOCR engine initialized (CPU)")

    def scan_frame(self, image_path: str, timestamp_ms: int) -> list[OCRRecord]:
        """对单张关键帧图像执行 OCR 识别。同步方法，需通过 to_thread 调用。"""
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
