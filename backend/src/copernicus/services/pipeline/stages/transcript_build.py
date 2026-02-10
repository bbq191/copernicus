"""Stage: Build fine-grained TranscriptEntry list from correction map."""

import logging

from copernicus.services.pipeline.base import (
    PipelineContext,
    ProgressCallback,
    TranscriptEntry,
)
from copernicus.utils.text import (
    format_timestamp,
    split_corrected_by_sub_sentences,
    split_original_by_sub_sentences,
)

logger = logging.getLogger(__name__)


class TranscriptBuildStage:
    name = "transcript_build"

    def should_run(self, ctx: PipelineContext) -> bool:
        return len(ctx.segments) > 0 and len(ctx.correction_map) > 0

    async def execute(
        self,
        ctx: PipelineContext,
        on_progress: ProgressCallback | None = None,
    ) -> PipelineContext:
        raw_entries: list[dict] = []
        noise_filtered = 0

        for i, seg in enumerate(ctx.segments):
            corrected = ctx.correction_map.get(i, seg.text)
            if corrected == "":
                noise_filtered += 1
                continue
            speaker_label = (
                f"Speaker {seg.speaker + 1}" if seg.speaker >= 0 else "Speaker 1"
            )

            subs = seg.sub_sentences
            if subs and len(subs) > 1:
                corrected_subs = split_corrected_by_sub_sentences(corrected, subs)
                original_subs = split_original_by_sub_sentences(seg.text, subs)
                for j, csub in enumerate(corrected_subs):
                    orig = original_subs[j] if j < len(original_subs) else csub.text
                    raw_entries.append({
                        "timestamp": format_timestamp(csub.start_ms),
                        "timestamp_ms": csub.start_ms,
                        "end_ms": csub.end_ms,
                        "speaker": speaker_label,
                        "text": orig,
                        "text_corrected": csub.text,
                    })
            else:
                raw_entries.append({
                    "timestamp": format_timestamp(seg.start_ms),
                    "timestamp_ms": seg.start_ms,
                    "end_ms": seg.end_ms,
                    "speaker": speaker_label,
                    "text": seg.text,
                    "text_corrected": corrected,
                })

        if noise_filtered > 0:
            logger.info("Noise filtered: %d segments removed", noise_filtered)

        logger.info("Fine-grained entries: %d", len(raw_entries))

        ctx.transcript_entries = [
            TranscriptEntry(
                timestamp=e["timestamp"],
                timestamp_ms=e["timestamp_ms"],
                end_ms=e["end_ms"],
                speaker=e["speaker"],
                text=e["text"],
                text_corrected=e["text_corrected"],
            )
            for e in raw_entries
        ]
        return ctx
