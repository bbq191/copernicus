"""TextCorrectionStage：置信度过滤与降级统计的传递。"""

from unittest.mock import AsyncMock, MagicMock

from copernicus.services.asr import Segment
from copernicus.services.corrector import CorrectionOutcome
from copernicus.services.pipeline.base import PipelineContext
from copernicus.services.pipeline.stages.text_correction import TextCorrectionStage


def _ctx(*confidences: float) -> PipelineContext:
    ctx = PipelineContext()
    ctx.segments = [
        Segment(text=f"第{i}句", start_ms=i * 1000, end_ms=i * 1000 + 900, confidence=c)
        for i, c in enumerate(confidences)
    ]
    return ctx


class TestTextCorrectionStage:
    async def test_only_low_confidence_segments_go_to_the_llm(self):
        corrector = MagicMock()
        corrector.correct_transcript = AsyncMock(return_value=CorrectionOutcome({1: "润色后"}, 1, 0))
        stage = TextCorrectionStage(corrector, confidence_threshold=0.9)

        ctx = await stage.execute(_ctx(0.99, 0.5, 0.95))

        sent = corrector.correct_transcript.call_args.args[0]
        assert sent == [{"id": 1, "text": "第1句"}]
        assert ctx.correction_map == {0: "第0句", 1: "润色后", 2: "第2句"}

    async def test_degradation_counts_are_carried_on_the_context(self):
        corrector = MagicMock()
        corrector.correct_transcript = AsyncMock(return_value=CorrectionOutcome({0: "x"}, 5, 2))
        ctx = await TextCorrectionStage(corrector).execute(_ctx(0.1))
        assert (ctx.correction_total_batches, ctx.correction_failed_batches) == (5, 2)

    async def test_all_confident_segments_skip_the_llm_entirely(self):
        corrector = MagicMock()
        corrector.correct_transcript = AsyncMock()
        ctx = await TextCorrectionStage(corrector, confidence_threshold=0.5).execute(_ctx(0.9, 0.8))
        corrector.correct_transcript.assert_not_awaited()
        assert ctx.correction_failed_batches == 0
