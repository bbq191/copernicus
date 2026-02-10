"""Stage: Speaker diarization smoothing + segment pre-merge."""

import logging

from copernicus.services.pipeline.base import PipelineContext, ProgressCallback
from copernicus.utils.text import pre_merge_segments, smooth_speakers

logger = logging.getLogger(__name__)


class SpeakerSmoothStage:
    name = "speaker_smooth"

    def __init__(self, pre_merge_gap_ms: int = 1000) -> None:
        self._pre_merge_gap_ms = pre_merge_gap_ms

    def should_run(self, ctx: PipelineContext) -> bool:
        return len(ctx.segments) > 0

    async def execute(
        self,
        ctx: PipelineContext,
        on_progress: ProgressCallback | None = None,
    ) -> PipelineContext:
        smooth_speakers(ctx.segments)

        raw_count = len(ctx.segments)
        ctx.segments = pre_merge_segments(ctx.segments, gap_ms=self._pre_merge_gap_ms)
        logger.info("Pre-merge: %d -> %d segments", raw_count, len(ctx.segments))
        return ctx
