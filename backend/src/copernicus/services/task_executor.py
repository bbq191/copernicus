"""任务的"干活"部分：把管线、摘要、合规审核串成各类任务的执行体。

状态机之外的一切（阶段切换、进度、结果与产物落盘）在这里；
任务的登记、调度、超时/取消与失败标记由 TaskStore 负责。

作者：afu
"""

import logging
import time
from pathlib import Path

from copernicus.config import Settings
from copernicus.exceptions import ServiceNotConfiguredError
from copernicus.schemas.compliance import ComplianceResponse
from copernicus.schemas.evaluation import EvaluationResponse, EvaluationResult
from copernicus.schemas.task import TaskStatus
from copernicus.schemas.transcription import TranscriptEntrySchema, TranscriptResponse
from copernicus.services.compliance import ComplianceService
from copernicus.services.evaluator import EvaluatorService
from copernicus.services.minutes_structure import MinutesStructurer
from copernicus.services.model_manager import ModelManager
from copernicus.services.persistence import PersistenceService
from copernicus.services.pipeline import PipelineService
from copernicus.services.task_state import TaskInfo
from copernicus.services.template_manager import FALLBACK_PROMPT, TemplateManager

logger = logging.getLogger(__name__)

# 管线阶段 → 任务状态
_PIPELINE_STAGE_STATUS: dict[str, TaskStatus] = {
    "video_preprocess": TaskStatus.EXTRACTING_FRAMES,
    "keyframe_extract": TaskStatus.EXTRACTING_FRAMES,
    "ocr_scan": TaskStatus.SCANNING_VISUAL,
    "face_detect": TaskStatus.SCANNING_VISUAL,
    "audio_preprocess": TaskStatus.PROCESSING_ASR,
    "asr_queued": TaskStatus.QUEUED_ASR,
    "asr_transcribe": TaskStatus.PROCESSING_ASR,
    "text_correction": TaskStatus.CORRECTING,
}


class TaskExecutor:
    def __init__(
        self,
        pipeline: PipelineService,
        persistence: PersistenceService,
        settings: Settings,
        evaluator: EvaluatorService | None = None,
        compliance: ComplianceService | None = None,
        model_manager: ModelManager | None = None,
        template_manager: TemplateManager | None = None,
        structurer: MinutesStructurer | None = None,
    ) -> None:
        self._structurer = structurer
        self._pipeline = pipeline
        self._persistence = persistence
        self._evaluator = evaluator
        self._compliance = compliance
        self._model_manager = model_manager
        self._template_manager = template_manager
        self._llm_is_local = settings.llm_provider == "ollama"

    # -- 服务是否可用：提交时先检查，失败立即返回 503，而不是等任务跑起来才失败 --

    def require_evaluator(self) -> EvaluatorService:
        if self._evaluator is None:
            raise ServiceNotConfiguredError("EvaluatorService not configured")
        return self._evaluator

    def require_compliance(self) -> ComplianceService:
        if self._compliance is None:
            raise ServiceNotConfiguredError("ComplianceService not configured")
        return self._compliance

    # -- 各类任务 ----------------------------------------------------------------

    async def text_evaluation(self, task: TaskInfo, text: str, template_id: str) -> None:
        evaluation = await self._evaluate_text(task, text, template_id)
        evaluation = await self._with_structure(evaluation, self._parent_entries(task))
        task.result = EvaluationResponse(
            raw_text="",
            corrected_text=text,
            evaluation=evaluation,
            processing_time_ms=0,
        )
        if task.parent_task_id:
            self._persistence.save_json(task.parent_task_id, "evaluation.json", evaluation)

    async def transcript(
        self,
        task: TaskInfo,
        media_path: Path,
        filename: str,
        hotwords: list[str] | None,
        *,
        visual_scan: bool = False,
    ) -> None:
        await self._run_pipeline(task, media_path, filename, hotwords, visual_scan)

    async def standard_minutes(
        self,
        task: TaskInfo,
        media_path: Path,
        filename: str,
        hotwords: list[str] | None,
        *,
        visual_scan: bool = False,
        generate_summary: bool = True,
        template_id: str = "universal",
    ) -> None:
        transcript = await self._run_pipeline(task, media_path, filename, hotwords, visual_scan)
        if generate_summary and self._evaluator:
            await self._generate_summary(task, transcript, template_id)

    async def compliance_audit(
        self,
        task: TaskInfo,
        transcript_entries: list[dict],
        rules_bytes: bytes,
        rules_filename: str,
    ) -> None:
        task.enter(TaskStatus.AUDITING)
        compliance = self.require_compliance()

        start = time.perf_counter()
        rules, few_shot_examples = compliance.parse_rules(rules_bytes, rules_filename)

        # 本地 LLM（Ollama）与 ASR 争用显存：先卸载 ASR。远端 LLM 不占本机显存，
        # 此时卸载只会让下一个转写任务白白重载数十秒
        if self._model_manager and self._llm_is_local:
            await self._model_manager.unload("asr")

        report = await compliance.audit(
            rules,
            transcript_entries,
            few_shot_examples=few_shot_examples,
            on_progress=task.set_progress,
            ocr_results=self._load_ocr_results(task),
        )
        response = ComplianceResponse(
            rules=rules,
            report=report,
            processing_time_ms=(time.perf_counter() - start) * 1000,
        )
        task.result = response
        if task.parent_task_id:
            self._persistence.save_json(task.parent_task_id, "compliance.json", response)

    # -- 内部 --------------------------------------------------------------------

    def _load_ocr_results(self, task: TaskInfo) -> list[dict] | None:
        """从持久化层加载转写任务时保存的 OCR 数据（合规审核的画面文字证据）。"""
        source_task_id = task.parent_task_id or task.task_id
        data = self._persistence.load_json(source_task_id, "ocr_results.json")
        if not data or not isinstance(data, list):
            return None
        logger.info("Loaded %d OCR records for compliance audit (task=%s)", len(data), source_task_id)
        return data

    def _parent_entries(self, task: TaskInfo) -> list[TranscriptEntrySchema]:
        """重新评估时，从父任务已保存的转写取句段（含人工校对后的文本与时间戳），供结构化提取回溯时间点。"""
        if not task.parent_task_id:
            return []
        data = self._persistence.load_json(task.parent_task_id, "transcript.json")
        if not data:
            return []
        try:
            return TranscriptResponse.model_validate(data).transcript
        except Exception as e:
            logger.warning("Task %s: parent transcript unreadable: %s", task.task_id, e)
            return []

    async def _with_structure(
        self, evaluation: EvaluationResult, entries: list[TranscriptEntrySchema]
    ) -> EvaluationResult:
        """给纪要补上行动项与决议。失败只降级为"未提取"，不影响纪要本身。"""
        if self._structurer is None or not self._structurer.enabled or not entries:
            return evaluation
        try:
            minutes = await self._structurer.extract(entries)
        except Exception as e:
            logger.warning("Structured minutes failed, keeping the plain summary: %s", e)
            return evaluation.model_copy(update={"structure_status": "failed"})
        return evaluation.model_copy(update={
            "action_items": minutes.action_items,
            "decisions": minutes.decisions,
            "structure_status": minutes.status,
        })

    def _template_prompt(self, template_id: str) -> str:
        if self._template_manager is None:
            return FALLBACK_PROMPT
        return self._template_manager.get_prompt(template_id)

    async def _evaluate_text(self, task: TaskInfo, text: str, template_id: str) -> EvaluationResult:
        """摘要评估：纯文本评估任务与标准纪要的摘要阶段共用。"""
        evaluator = self.require_evaluator()
        task.enter(TaskStatus.EVALUATING)
        return await evaluator.evaluate(
            text, self._template_prompt(template_id), on_progress=task.set_progress
        )

    async def _run_pipeline(
        self,
        task: TaskInfo,
        media_path: Path,
        filename: str,
        hotwords: list[str] | None,
        visual_scan: bool,
    ) -> TranscriptResponse:
        """执行转写管线，随阶段切换任务状态，并保存 transcript.json。"""
        task.status = TaskStatus.PROCESSING_ASR

        def on_stage_change(stage_name: str) -> None:
            new_status = _PIPELINE_STAGE_STATUS.get(stage_name)
            if new_status:
                task.enter(new_status)

        result = await self._pipeline.process_transcript(
            media_path, filename, hotwords,
            on_progress=task.set_progress,
            on_stage_change=on_stage_change,
            task_id=task.task_id,
            visual_scan=visual_scan,
        )

        response = TranscriptResponse(
            transcript=[
                TranscriptEntrySchema(
                    timestamp=entry.timestamp,
                    timestamp_ms=entry.timestamp_ms,
                    end_ms=entry.end_ms,
                    speaker=entry.speaker,
                    text=entry.text,
                    text_corrected=entry.text_corrected,
                )
                for entry in result.transcript
            ],
            processing_time_ms=result.processing_time_ms,
            correction_total_batches=result.correction_total_batches,
            correction_failed_batches=result.correction_failed_batches,
        )
        task.result = response
        self._persistence.save_json(task.task_id, "transcript.json", response)
        return response

    async def _generate_summary(
        self, task: TaskInfo, transcript: TranscriptResponse, template_id: str
    ) -> None:
        """标准纪要的摘要阶段。转写已落盘，摘要失败不应让整个任务变成失败：

        否则内存里是 FAILED（同一文件重传要重跑 ASR），重启后又因 transcript.json 存在而恢复为 COMPLETED，
        前后状态不一致。这里只记录警告；前端发现没有摘要时会自动重新生成。
        """
        full_text = "\n".join(e.text_corrected for e in transcript.transcript)
        if not full_text.strip():
            return
        try:
            evaluation = await self._evaluate_text(task, full_text, template_id)
        except Exception as e:
            logger.warning("Task %s: summary failed, transcript kept: %s", task.task_id, e)
            return
        evaluation = await self._with_structure(evaluation, transcript.transcript)
        self._persistence.save_json(task.task_id, "evaluation.json", evaluation)
        logger.info("Task %s: summary generated (template=%s)", task.task_id, template_id)
