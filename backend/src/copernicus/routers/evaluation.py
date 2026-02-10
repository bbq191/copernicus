from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, File

from copernicus.config import settings
from copernicus.dependencies import get_evaluator, get_pipeline, get_task_store
from copernicus.exceptions import CopernicusError
from copernicus.schemas.evaluation import EvaluationResponse, EvaluationResult
from copernicus.schemas.task import TaskStatus, TaskSubmitResponse
from copernicus.services.evaluator import EvaluatorService
from copernicus.services.pipeline import PipelineService
from copernicus.services.task_store import TaskStore
from copernicus.utils.request import parse_hotwords

router = APIRouter(prefix="/api/v1", tags=["evaluation"])


@router.post("/evaluate", response_model=EvaluationResponse)
async def evaluate_audio(
    file: UploadFile = File(...),
    hotwords: str | None = Form(default=None),
    pipeline: PipelineService = Depends(get_pipeline),
    evaluator: EvaluatorService = Depends(get_evaluator),
) -> EvaluationResponse:
    """Upload audio, run ASR + correction + content evaluation."""
    audio_bytes = await file.read()

    if len(audio_bytes) > settings.max_upload_size_bytes:
        raise HTTPException(status_code=413, detail="File too large")

    hw = parse_hotwords(hotwords)

    try:
        result = await pipeline.process(audio_bytes, file.filename or "upload.bin", hw)
        evaluation = await evaluator.evaluate(result.corrected_text)
    except CopernicusError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return EvaluationResponse(
        raw_text=result.raw_text,
        corrected_text=result.corrected_text,
        evaluation=evaluation,
        processing_time_ms=result.processing_time_ms,
    )


@router.post("/evaluate/async", response_model=TaskSubmitResponse, status_code=202)
async def submit_evaluate_task(
    file: UploadFile = File(...),
    hotwords: str | None = Form(default=None),
    store: TaskStore = Depends(get_task_store),
) -> TaskSubmitResponse:
    """Submit an async evaluation task. Poll GET /tasks/{task_id} for progress."""
    audio_bytes = await file.read()

    if len(audio_bytes) > settings.max_upload_size_bytes:
        raise HTTPException(status_code=413, detail="File too large")

    hw = parse_hotwords(hotwords)
    task_id = store.submit_evaluation(audio_bytes, file.filename or "upload.bin", hw)

    return TaskSubmitResponse(task_id=task_id, status=TaskStatus.PENDING)


@router.post("/evaluate/text", response_model=EvaluationResult)
async def evaluate_text(
    text: str = Form(...),
    evaluator: EvaluatorService = Depends(get_evaluator),
) -> EvaluationResult:
    """Evaluate a text transcript directly (no ASR needed)."""
    if not text.strip():
        raise HTTPException(status_code=422, detail="Text must not be empty")
    return await evaluator.evaluate(text)


@router.post("/evaluate/text/async", response_model=TaskSubmitResponse, status_code=202)
async def submit_text_evaluation_task(
    text: str = Form(...),
    parent_task_id: str | None = Form(default=None),
    store: TaskStore = Depends(get_task_store),
) -> TaskSubmitResponse:
    """Submit an async text evaluation task. Poll GET /tasks/{task_id} for progress."""
    if not text.strip():
        raise HTTPException(status_code=422, detail="Text must not be empty")
    task_id = store.submit_text_evaluation(text, parent_task_id=parent_task_id)
    return TaskSubmitResponse(task_id=task_id, status=TaskStatus.PENDING)
