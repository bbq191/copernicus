"""Visual analysis schemas for multi-modal audit pipeline.

Author: afu
"""

from typing import Literal

from pydantic import BaseModel, Field


class KeyFrame(BaseModel):
    """A single extracted keyframe from video."""

    index: int
    timestamp_ms: int
    path: str


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


class VisualAnalysisResult(BaseModel):
    """Aggregated visual analysis output."""

    keyframes: list[KeyFrame] = Field(default_factory=list)
    ocr_records: list[OCRRecord] = Field(default_factory=list)
    visual_events: list[VisualEvent] = Field(default_factory=list)
