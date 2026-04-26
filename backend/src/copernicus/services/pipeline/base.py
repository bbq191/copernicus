"""Pipeline 核心抽象：PipelineContext 数据总线与 Stage 协议。"""

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
    """带时间戳的单条转写记录。"""

    timestamp: str
    timestamp_ms: int
    end_ms: int
    speaker: str
    text: str
    text_corrected: str


@dataclass
class TranscriptResult:
    """转写 Pipeline 的输出结果。"""

    transcript: list[TranscriptEntry] = field(default_factory=list)
    processing_time_ms: float = 0.0


@dataclass
class PipelineContext:
    """贯穿所有 Stage 的共享数据总线。"""

    # Input
    task_id: str = ""
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

    # Visual (video pipeline)
    video_path: Path | None = None
    keyframes: list | None = None
    ocr_results: list | None = None
    visual_events: list | None = None
    media_type: str = "audio"
    visual_scan: bool = False  # True 时才执行关键帧提取/OCR/人脸检测

    # Timing
    processing_times: dict[str, float] = field(default_factory=dict)


@runtime_checkable
class Stage(Protocol):
    """所有 Pipeline Stage 必须实现的协议接口。"""

    name: str

    async def execute(
        self,
        ctx: PipelineContext,
        on_progress: ProgressCallback | None = None,
    ) -> PipelineContext: ...

    def should_run(self, ctx: PipelineContext) -> bool: ...
