"""Face detection service using ultralytics YOLO (CPU-only).

Author: afu
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from copernicus.schemas.visual import VisualEvent

if TYPE_CHECKING:
    from copernicus.config import Settings

logger = logging.getLogger(__name__)


class FaceDetectorService:
    """Lazy-loaded YOLO face detector with timeline analysis."""

    def __init__(self, settings: Settings) -> None:
        self._model_path = settings.face_detect_model
        self._confidence = settings.face_detect_confidence
        self._missing_threshold_ms = settings.face_missing_threshold_ms
        self._model = None

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        model_path = Path(self._model_path)
        if not model_path.exists():
            raise FileNotFoundError(
                f"Face detection model not found: {model_path}. "
                f"Download yolov8n-face.pt and place it in backend/models/"
            )
        from ultralytics import YOLO

        self._model = YOLO(str(model_path))
        logger.info("YOLO face model loaded from %s (CPU)", model_path)

    def detect_frame(self, image_path: str) -> list[dict]:
        """Detect faces in a single frame. Synchronous -- call via to_thread."""
        self._ensure_model()
        assert self._model is not None

        results = self._model.predict(
            source=image_path, device="cpu", conf=self._confidence, verbose=False
        )
        faces: list[dict] = []
        if results and len(results) > 0:
            for box in results[0].boxes:
                xyxy = box.xyxy[0].tolist()
                faces.append({
                    "bbox": [round(v, 1) for v in xyxy],
                    "confidence": round(float(box.conf[0]), 4),
                })
        return faces

    def analyze_face_timeline(
        self,
        frame_results: list[dict],
        interval_ms: int,
    ) -> list[VisualEvent]:
        """Analyze per-frame face detection results into timeline events.

        Args:
            frame_results: List of {timestamp_ms, face_count, max_confidence, frame_path}
            interval_ms: Approximate interval between frames in milliseconds.

        Returns:
            List of VisualEvent (face_detected / face_missing).
        """
        if not frame_results:
            return []

        events: list[VisualEvent] = []
        sorted_results = sorted(frame_results, key=lambda r: r["timestamp_ms"])

        # State machine: track current state and segment boundaries
        state: str | None = None  # "detected" | "missing"
        seg_start_ms = 0
        seg_confidence = 0.0
        seg_frame_path: str | None = None

        for fr in sorted_results:
            has_face = fr["face_count"] > 0
            current = "detected" if has_face else "missing"

            if state is None:
                state = current
                seg_start_ms = fr["timestamp_ms"]
                seg_confidence = fr["max_confidence"]
                seg_frame_path = fr["frame_path"]
                continue

            if current != state:
                # Close previous segment
                end_ms = fr["timestamp_ms"]
                self._emit_event(
                    events, state, seg_start_ms, end_ms,
                    seg_confidence, seg_frame_path,
                )
                # Start new segment
                state = current
                seg_start_ms = fr["timestamp_ms"]
                seg_confidence = fr["max_confidence"]
                seg_frame_path = fr["frame_path"]
            else:
                # Update running max confidence
                if fr["max_confidence"] > seg_confidence:
                    seg_confidence = fr["max_confidence"]

        # Close final segment
        if state is not None and sorted_results:
            end_ms = sorted_results[-1]["timestamp_ms"] + interval_ms
            self._emit_event(
                events, state, seg_start_ms, end_ms,
                seg_confidence, seg_frame_path,
            )

        return events

    def _emit_event(
        self,
        events: list[VisualEvent],
        state: str,
        start_ms: int,
        end_ms: int,
        confidence: float,
        frame_path: str | None,
    ) -> None:
        """Emit a VisualEvent, filtering short face_missing segments."""
        duration = end_ms - start_ms
        if state == "missing" and duration < self._missing_threshold_ms:
            return
        event_type = "face_detected" if state == "detected" else "face_missing"
        events.append(
            VisualEvent(
                event_type=event_type,
                start_ms=start_ms,
                end_ms=end_ms,
                confidence=round(confidence, 4),
                frame_path=frame_path,
            )
        )
