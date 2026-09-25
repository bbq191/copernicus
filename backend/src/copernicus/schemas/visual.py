"""Visual analysis schemas for multi-modal audit pipeline.

Author: afu
"""

from typing import Literal

from pydantic import BaseModel, Field


class OCRRecord(BaseModel):
    """OCR recognition result for a keyframe."""

    timestamp_ms: int
    text: str
    confidence: float
    frame_path: str
    bbox: list[list[int]] = Field(default_factory=list)


class VisualEvent(BaseModel):
    """A detected visual event (face, scene change, etc.)."""

    event_type: Literal["face_detected", "face_missing", "scene_change"]
    start_ms: int
    end_ms: int
    confidence: float
    frame_path: str | None = None
