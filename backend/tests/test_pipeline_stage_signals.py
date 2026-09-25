"""编排器在每个阶段开始时通知外层，任务状态才能随阶段切换。"""

from copernicus.schemas.task import TaskStatus
from copernicus.services.pipeline.base import PipelineContext
from copernicus.services.pipeline.orchestrator import PipelineOrchestrator
from copernicus.services.task_state import TaskInfo
from copernicus.services.task_executor import _PIPELINE_STAGE_STATUS


class _Stage:
    def __init__(self, name: str, run: bool = True) -> None:
        self.name = name
        self._run = run

    def should_run(self, ctx: PipelineContext) -> bool:
        return self._run

    async def execute(self, ctx, on_progress=None):
        return ctx


class TestStageStartSignal:
    async def test_every_executed_stage_is_announced_even_without_progress(self):
        seen: list[str] = []
        orchestrator = (
            PipelineOrchestrator()
            .register(_Stage("video_preprocess"))
            .register(_Stage("ocr_scan", run=False))
            .register(_Stage("asr_transcribe"))
        )
        await orchestrator.run(
            PipelineContext(), on_stage_progress=lambda name, *_: seen.append(name)
        )
        assert seen == ["video_preprocess", "asr_transcribe"]


class TestStatusMapping:
    def test_all_mapped_statuses_are_valid(self):
        for status in _PIPELINE_STAGE_STATUS.values():
            TaskStatus(status)

    def test_queued_asr_is_shown_at_the_asr_progress_mark(self):
        task = TaskInfo("t")
        task.enter(TaskStatus.QUEUED_ASR)
        assert task.progress.percent == 20.0
