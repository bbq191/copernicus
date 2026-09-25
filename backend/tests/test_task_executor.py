"""TaskExecutor：各类任务的执行体（管线状态切换、摘要降级、合规审核的显存与证据处理）。"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from copernicus.config import Settings
from copernicus.exceptions import ServiceNotConfiguredError
from copernicus.schemas.evaluation import EvaluationResult
from copernicus.schemas.task import TaskStatus
from copernicus.services.pipeline.base import TranscriptEntry, TranscriptResult
from copernicus.services.task_executor import TaskExecutor
from copernicus.services.task_state import TaskInfo


def _entry(text: str = "你好") -> TranscriptEntry:
    return TranscriptEntry(
        timestamp="00:01", timestamp_ms=1000, end_ms=2000, speaker="说话人1",
        text=text, text_corrected=text,
    )


def _pipeline(*entries: TranscriptEntry, stages: tuple[str, ...] = ()):
    seen_status: list[TaskStatus] = []
    pipeline = MagicMock()

    async def process(media, filename, hotwords, *, on_progress, on_stage_change, task_id, visual_scan):
        for stage in stages:
            on_stage_change(stage)
            seen_status.append(task_ref[0].status)
        return TranscriptResult(
            transcript=list(entries), processing_time_ms=12.0,
            correction_total_batches=3, correction_failed_batches=1,
        )

    pipeline.process_transcript = process
    task_ref: list[TaskInfo] = []
    return pipeline, task_ref, seen_status


def _executor(pipeline=None, **kwargs) -> tuple[TaskExecutor, MagicMock]:
    persistence = MagicMock()
    persistence.load_json.return_value = None
    return TaskExecutor(pipeline or MagicMock(), persistence, Settings(llm_provider="ollama"), **kwargs), persistence


def _evaluator(result=None, error: Exception | None = None):
    ev = MagicMock()
    ev.evaluate = AsyncMock(side_effect=error, return_value=result or EvaluationResult(title="纪要", summary="s"))
    return ev


def _evaluation_saved(persistence) -> bool:
    return any(c.args[1] == "evaluation.json" for c in persistence.save_json.call_args_list)


class TestTranscript:
    async def test_stage_changes_drive_task_status_and_result_is_saved(self, tmp_path):
        pipeline, ref, seen = _pipeline(
            _entry(), stages=("video_preprocess", "ocr_scan", "asr_queued", "asr_transcribe", "text_correction"),
        )
        executor, persistence = _executor(pipeline)
        task = TaskInfo("t" * 32)
        ref.append(task)

        await executor.transcript(task, tmp_path / "v.mp4", "v.mp4", None, visual_scan=True)

        assert seen == [
            TaskStatus.EXTRACTING_FRAMES, TaskStatus.SCANNING_VISUAL,
            TaskStatus.QUEUED_ASR, TaskStatus.PROCESSING_ASR, TaskStatus.CORRECTING,
        ]
        assert task.result.correction_failed_batches == 1 and task.result.transcript[0].text == "你好"
        persistence.save_json.assert_called_once_with(task.task_id, "transcript.json", task.result)

    async def test_unmapped_stage_names_leave_the_status_alone(self, tmp_path):
        pipeline, ref, seen = _pipeline(_entry(), stages=("speaker_smooth",))
        executor, _ = _executor(pipeline)
        task = TaskInfo("t" * 32)
        ref.append(task)
        await executor.transcript(task, tmp_path / "a.wav", "a.wav", None)
        assert seen == [TaskStatus.PROCESSING_ASR]


class TestStandardMinutes:
    async def _run(self, tmp_path, evaluator, *entries, generate_summary=True):
        pipeline, ref, _ = _pipeline(*entries)
        executor, persistence = _executor(pipeline, evaluator=evaluator)
        task = TaskInfo("t" * 32)
        ref.append(task)
        await executor.standard_minutes(
            task, tmp_path / "a.wav", "a.wav", None, generate_summary=generate_summary, template_id="weekly",
        )
        return task, persistence

    async def test_summary_is_generated_and_saved_with_the_chosen_template(self, tmp_path):
        evaluator = _evaluator()
        task, persistence = await self._run(tmp_path, evaluator, _entry("今天开会"))
        assert _evaluation_saved(persistence)
        assert evaluator.evaluate.call_args.args[0] == "今天开会"

    async def test_summary_failure_keeps_the_transcript_and_does_not_raise(self, tmp_path):
        task, persistence = await self._run(tmp_path, _evaluator(error=RuntimeError("LLM down")), _entry())
        assert task.result is not None and not _evaluation_saved(persistence)

    async def test_empty_transcript_skips_the_summary(self, tmp_path):
        evaluator = _evaluator()
        await self._run(tmp_path, evaluator, _entry("  "))
        evaluator.evaluate.assert_not_called()

    async def test_summary_can_be_turned_off(self, tmp_path):
        evaluator = _evaluator()
        await self._run(tmp_path, evaluator, _entry(), generate_summary=False)
        evaluator.evaluate.assert_not_called()

    async def test_no_evaluator_configured_means_no_summary(self, tmp_path):
        task, persistence = await self._run(tmp_path, None, _entry())
        assert task.result is not None and not _evaluation_saved(persistence)


class TestTextEvaluation:
    async def test_result_is_attached_and_saved_under_the_parent_task(self):
        executor, persistence = _executor(evaluator=_evaluator())
        task = TaskInfo("c" * 32, eval_only=True, parent_task_id="p" * 32)

        await executor.text_evaluation(task, "文本", "universal")

        assert task.result.evaluation.title == "纪要"
        persistence.save_json.assert_called_once()
        assert persistence.save_json.call_args.args[:2] == ("p" * 32, "evaluation.json")

    async def test_without_parent_nothing_is_persisted(self):
        executor, persistence = _executor(evaluator=_evaluator())
        await executor.text_evaluation(TaskInfo("c" * 32, eval_only=True), "文本", "universal")
        persistence.save_json.assert_not_called()

    async def test_missing_evaluator_is_reported(self):
        executor, _ = _executor()
        with pytest.raises(ServiceNotConfiguredError):
            await executor.text_evaluation(TaskInfo("c" * 32, eval_only=True), "文本", "universal")


class TestComplianceAudit:
    def _setup(self, *, provider="ollama", ocr=None):
        compliance = MagicMock()
        compliance.parse_rules.return_value = (["rule"], ["example"])
        compliance.audit = AsyncMock(return_value=MagicMock())
        manager = MagicMock(unload=AsyncMock())
        persistence = MagicMock()
        persistence.load_json.return_value = ocr
        executor = TaskExecutor(
            MagicMock(), persistence, Settings(llm_provider=provider),
            compliance=compliance, model_manager=manager,
        )
        return executor, compliance, manager, persistence

    async def test_local_llm_unloads_asr_first_and_status_is_auditing(self, monkeypatch):
        executor, compliance, manager, persistence = self._setup()
        monkeypatch.setattr("copernicus.services.task_executor.ComplianceResponse", MagicMock())
        task = TaskInfo("c" * 32, eval_only=True, parent_task_id="p" * 32)

        await executor.compliance_audit(task, [{"text": "x"}], b"rules", "r.csv")

        assert task.status == TaskStatus.AUDITING
        manager.unload.assert_awaited_once_with("asr")
        assert compliance.audit.call_args.kwargs["few_shot_examples"] == ["example"]
        persistence.save_json.assert_called_once()
        assert persistence.save_json.call_args.args[:2] == ("p" * 32, "compliance.json")

    async def test_remote_llm_leaves_asr_loaded(self, monkeypatch):
        executor, _, manager, _ = self._setup(provider="openai")
        monkeypatch.setattr("copernicus.services.task_executor.ComplianceResponse", MagicMock())
        await executor.compliance_audit(TaskInfo("c" * 32, eval_only=True), [], b"r", "r.csv")
        manager.unload.assert_not_awaited()

    async def test_ocr_evidence_comes_from_the_parent_task(self, monkeypatch):
        executor, compliance, _, persistence = self._setup(ocr=[{"text": "免责声明"}])
        monkeypatch.setattr("copernicus.services.task_executor.ComplianceResponse", MagicMock())
        task = TaskInfo("c" * 32, eval_only=True, parent_task_id="p" * 32)

        await executor.compliance_audit(task, [], b"r", "r.csv")

        persistence.load_json.assert_called_with("p" * 32, "ocr_results.json")
        assert compliance.audit.call_args.kwargs["ocr_results"] == [{"text": "免责声明"}]

    async def test_non_list_ocr_data_is_ignored(self, monkeypatch):
        executor, compliance, _, _ = self._setup(ocr={"unexpected": True})
        monkeypatch.setattr("copernicus.services.task_executor.ComplianceResponse", MagicMock())
        await executor.compliance_audit(TaskInfo("c" * 32, eval_only=True), [], b"r", "r.csv")
        assert compliance.audit.call_args.kwargs["ocr_results"] is None

    async def test_missing_service_is_reported(self):
        executor, _ = _executor()
        with pytest.raises(ServiceNotConfiguredError):
            await executor.compliance_audit(TaskInfo("c" * 32, eval_only=True), [], b"r", "r.csv")
