"""Stage: OCR scanning of keyframes using RapidOCR.

Scans each keyframe for text content and persists results as ocr_results.json.

Author: afu
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

from copernicus.services.pipeline.base import PipelineContext
from copernicus.utils.types import ProgressCallback

if TYPE_CHECKING:
    from copernicus.services.ocr import OCRService
    from copernicus.services.persistence import PersistenceService

logger = logging.getLogger(__name__)


class OCRScanStage:
    name = "ocr_scan"

    def __init__(
        self,
        ocr_service: OCRService,
        persistence: PersistenceService,
        *,
        enabled: bool = True,
    ) -> None:
        self._ocr = ocr_service
        self._persistence = persistence
        self._enabled = enabled

    def should_run(self, ctx: PipelineContext) -> bool:
        return self._enabled and ctx.keyframes is not None and len(ctx.keyframes) > 0

    async def execute(
        self,
        ctx: PipelineContext,
        on_progress: ProgressCallback | None = None,
    ) -> PipelineContext:
        if not ctx.keyframes or not ctx.task_id:
            return ctx

        frames_dir = self._persistence.frames_dir(ctx.task_id)
        all_records = []
        total = len(ctx.keyframes)

        for i, kf in enumerate(ctx.keyframes):
            image_path = str(frames_dir / kf["path"])
            timestamp_ms = kf["timestamp_ms"]

            records = await asyncio.to_thread(
                self._ocr.scan_frame, image_path, timestamp_ms
            )
            all_records.extend(records)

            if on_progress:
                on_progress(i + 1, total)

        ctx.ocr_results = [r.model_dump() for r in all_records]
        logger.info(
            "OCR scan completed: %d text regions from %d frames (task %s)",
            len(all_records), total, ctx.task_id,
        )

        # Persist ocr_results.json
        dest = self._persistence.task_dir(ctx.task_id) / "ocr_results.json"
        dest.write_text(
            json.dumps(ctx.ocr_results, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        return ctx
