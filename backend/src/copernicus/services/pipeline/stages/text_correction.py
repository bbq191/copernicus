"""Stage: Four-phase text correction via CorrectorService."""

import logging

from copernicus.services.corrector import CorrectorService
from copernicus.services.pipeline.base import PipelineContext, ProgressCallback

logger = logging.getLogger(__name__)


class TextCorrectionStage:
    name = "text_correction"

    def __init__(
        self,
        corrector_service: CorrectorService,
        confidence_threshold: float = 0.95,
    ) -> None:
        self._corrector = corrector_service
        self._confidence_threshold = confidence_threshold

    def should_run(self, ctx: PipelineContext) -> bool:
        return len(ctx.segments) > 0

    async def execute(
        self,
        ctx: PipelineContext,
        on_progress: ProgressCallback | None = None,
    ) -> PipelineContext:
        segments = ctx.segments
        has_confidence = any(seg.confidence > 0.0 for seg in segments)

        if has_confidence:
            skipped = sum(
                1 for seg in segments if seg.confidence >= self._confidence_threshold
            )
            logger.info(
                "Transcript confidence filter: %d/%d above threshold (%.2f)",
                skipped,
                len(segments),
                self._confidence_threshold,
            )
            if skipped == len(segments):
                ctx.correction_map = {i: seg.text for i, seg in enumerate(segments)}
                return ctx
            needs_correction = [
                seg.confidence < self._confidence_threshold for seg in segments
            ]
        else:
            needs_correction = [True] * len(segments)

        entries: list[dict] = []
        for i, seg in enumerate(segments):
            if needs_correction[i]:
                entries.append({"id": i, "text": seg.text})

        if not entries:
            ctx.correction_map = {i: seg.text for i, seg in enumerate(segments)}
            return ctx

        logger.info(
            "Transcript: correcting %d/%d segments via JSON-to-JSON",
            len(entries),
            len(segments),
        )

        outcome = await self._corrector.correct_transcript(entries, on_progress=on_progress)

        ctx.correction_map = {i: outcome.texts.get(i, seg.text) for i, seg in enumerate(segments)}
        ctx.correction_total_batches = outcome.total_batches
        ctx.correction_failed_batches = outcome.failed_batches
        return ctx
