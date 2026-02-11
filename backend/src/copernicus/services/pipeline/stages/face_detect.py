"""Stage: Face detection on keyframes using YOLO.

Detects faces per frame, analyzes the timeline for face presence/absence,
and persists results as visual_events.json.

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
    from copernicus.services.face_detector import FaceDetectorService
    from copernicus.services.persistence import PersistenceService

logger = logging.getLogger(__name__)


class FaceDetectStage:
    name = "face_detect"

    def __init__(
        self,
        face_detector: FaceDetectorService,
        persistence: PersistenceService,
        *,
        enabled: bool = True,
        interval_ms: int = 2000,
    ) -> None:
        self._detector = face_detector
        self._persistence = persistence
        self._enabled = enabled
        self._interval_ms = interval_ms

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
        frame_results: list[dict] = []
        total = len(ctx.keyframes)

        for i, kf in enumerate(ctx.keyframes):
            image_path = str(frames_dir / kf["path"])
            timestamp_ms = kf["timestamp_ms"]

            faces = await asyncio.to_thread(self._detector.detect_frame, image_path)
            max_conf = max((f["confidence"] for f in faces), default=0.0)
            frame_results.append({
                "timestamp_ms": timestamp_ms,
                "face_count": len(faces),
                "max_confidence": max_conf,
                "frame_path": kf["path"],
            })

            if on_progress:
                on_progress(i + 1, total)

        # Analyze timeline
        events = self._detector.analyze_face_timeline(frame_results, self._interval_ms)
        ctx.visual_events = [e.model_dump() for e in events]
        logger.info(
            "Face detection completed: %d events from %d frames (task %s)",
            len(events), total, ctx.task_id,
        )

        # Persist visual_events.json
        dest = self._persistence.task_dir(ctx.task_id) / "visual_events.json"
        dest.write_text(
            json.dumps(ctx.visual_events, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        return ctx
