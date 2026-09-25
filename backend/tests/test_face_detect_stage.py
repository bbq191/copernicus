"""人脸检测阶段：末段时长取关键帧的实际间隔。"""

from unittest.mock import MagicMock

from copernicus.services.pipeline.base import PipelineContext
from copernicus.services.pipeline.stages.face_detect import FaceDetectStage, _typical_gap_ms


def test_typical_gap_is_the_median_spacing():
    frames = [{"timestamp_ms": t} for t in (0, 50000, 100000, 100500, 150000)]
    assert _typical_gap_ms(frames) == 50000
    assert _typical_gap_ms([{"timestamp_ms": 0}]) == 0


async def test_configured_interval_is_only_a_fallback():
    detector = MagicMock()
    detector.detect_frame.return_value = []
    detector.analyze_face_timeline.return_value = []
    persistence = MagicMock()
    ctx = PipelineContext(task_id="t" * 32)
    ctx.keyframes = [
        {"timestamp_ms": 0, "path": "0001.jpg"},
        {"timestamp_ms": 50000, "path": "0002.jpg"},
    ]

    await FaceDetectStage(detector, persistence, interval_ms=2000).execute(ctx)

    assert detector.analyze_face_timeline.call_args.args[1] == 50000
