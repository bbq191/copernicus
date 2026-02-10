"""Pipeline core abstractions: PipelineContext and Stage protocol."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from copernicus.services.asr import ASRResult, Segment
from copernicus.utils.types import ProgressCallback

logger = logging.getLogger(__name__)

# (stage_name, stage_index, total_stages, current, total)
StageProgressCallback = Callable[[str, int, int, int, int], None]


@dataclass
class TranscriptEntry:
    """A single timestamped transcript entry."""

    timestamp: str
    timestamp_ms: int
    end_ms: int
    speaker: str
    text: str
    text_corrected: str


@dataclass
class TranscriptResult:
    """Output of the transcript pipeline."""

    transcript: list[TranscriptEntry] = field(default_factory=list)
    processing_time_ms: float = 0.0


@dataclass
class PipelineContext:
    """Shared data bus passed through all stages."""

    # Input
    audio_bytes: bytes | None = None
    filename: str = ""
    hotwords: list[str] | None = None

    # Pipeline mode control
    sentence_timestamp: bool = True

    # Audio preprocessing
    wav_path: Path | None = None

    # ASR output
    asr_result: ASRResult | None = None
    segments: list[Segment] = field(default_factory=list)

    # Correction output (id -> corrected text)
    correction_map: dict[int, str] = field(default_factory=dict)

    # Transcript output
    transcript_entries: list[TranscriptEntry] = field(default_factory=list)

    # Timing
    processing_times: dict[str, float] = field(default_factory=dict)


@runtime_checkable
class Stage(Protocol):
    """Protocol that all pipeline stages must implement."""

    name: str

    async def execute(
        self,
        ctx: PipelineContext,
        on_progress: ProgressCallback | None = None,
    ) -> PipelineContext: ...

    def should_run(self, ctx: PipelineContext) -> bool: ...
