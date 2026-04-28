import json
import re

from fastapi import APIRouter, Depends, Form, HTTPException, Request

from copernicus.dependencies import get_task_store
from copernicus.schemas.task import TaskStatus, TaskSubmitResponse
from copernicus.services.task_store import TaskStore

router = APIRouter(prefix="/api/v1", tags=["基础 AI"])

# 第三方格式：[2026-04-17 14:29:37]{...JSON...}
_THIRD_PARTY_RE = re.compile(r"^\[[^\]]+\](\{.+\})$", re.DOTALL)


def _extract_transcript(raw: str) -> str:
    """从第三方格式中提取 content 字段；解析失败则原文返回。"""
    m = _THIRD_PARTY_RE.match(raw.strip())
    if m:
        try:
            data = json.loads(m.group(1))
            content = data.get("content", "")
            if content:
                return content
        except json.JSONDecodeError:
            pass
    return raw


@router.post(
    "/evaluate/text/async",
    response_model=TaskSubmitResponse,
    status_code=202,
    summary="提交纯文本评估任务",
)
async def submit_text_evaluation_task(
    text: str = Form(...),
    parent_task_id: str | None = Form(default=None),
    store: TaskStore = Depends(get_task_store),
) -> TaskSubmitResponse:
    """对已有文本执行 Map-Reduce 评估，生成评分与摘要。

    适用于已有转写文本、不需要重新 ASR 的场景。长文本自动分段后并发提取要点，
    再由 Reduce 阶段合并生成最终 JSON（含标题、分类、评分、摘要）。

    `parent_task_id` 可选，填写后评估结果将写入对应任务的
    `evaluation.json`，供 `GET /tasks/{task_id}/results` 返回。
    """
    if not text.strip():
        raise HTTPException(status_code=422, detail="Text must not be empty")
    task_id = store.submit_text_evaluation(text, parent_task_id=parent_task_id)
    return TaskSubmitResponse(task_id=task_id, status=TaskStatus.PENDING)


@router.post(
    "/evaluate/transcript/async",
    response_model=TaskSubmitResponse,
    status_code=202,
    summary="接收第三方转写并评估",
)
async def submit_transcript_evaluation_task(
    request: Request,
    store: TaskStore = Depends(get_task_store),
) -> TaskSubmitResponse:
    """接收第三方 ASR 转写结果，提取正文后生成评分与摘要。

    直接接受原始请求体（`text/plain`），支持两种格式：

    - **第三方格式**：`[时间戳]{JSON}`，自动提取 JSON 中的 `content` 字段。
    - **纯文本**：直接作为转写内容处理。

    无需对内容做任何转义，适合第三方系统 webhook 直推。
    """
    raw = (await request.body()).decode("utf-8")
    transcript = _extract_transcript(raw)
    if not transcript.strip():
        raise HTTPException(status_code=422, detail="Text must not be empty")
    task_id = store.submit_text_evaluation(transcript)
    return TaskSubmitResponse(task_id=task_id, status=TaskStatus.PENDING)
