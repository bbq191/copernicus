import json
import re

from fastapi import APIRouter, Depends, Form, HTTPException, Request

from copernicus.dependencies import get_task_store
from copernicus.schemas.task import TaskStatus, TaskSubmitResponse
from copernicus.services.task_store import TaskStore

router = APIRouter(prefix="/api/v1", tags=["evaluation"])

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


@router.post("/evaluate/text/async", response_model=TaskSubmitResponse, status_code=202)
async def submit_text_evaluation_task(
    text: str = Form(...),
    parent_task_id: str | None = Form(default=None),
    store: TaskStore = Depends(get_task_store),
) -> TaskSubmitResponse:
    """提交异步文本评估任务，通过 GET /tasks/{task_id} 轮询进度。"""
    if not text.strip():
        raise HTTPException(status_code=422, detail="Text must not be empty")
    task_id = store.submit_text_evaluation(text, parent_task_id=parent_task_id)
    return TaskSubmitResponse(task_id=task_id, status=TaskStatus.PENDING)


@router.post("/evaluate/transcript/async", response_model=TaskSubmitResponse, status_code=202)
async def submit_transcript_evaluation_task(
    request: Request,
    store: TaskStore = Depends(get_task_store),
) -> TaskSubmitResponse:
    """接收第三方转写结果，提取正文后生成带评分的50字摘要。

    直接接受原始请求体（text/plain），第三方无需对内容做任何转义。
    支持两种格式：
    - 第三方格式：`[时间戳]{JSON}`，自动提取 JSON 中的 content 字段
    - 纯文本：直接作为转写内容处理
    """
    raw = (await request.body()).decode("utf-8")
    transcript = _extract_transcript(raw)
    if not transcript.strip():
        raise HTTPException(status_code=422, detail="Text must not be empty")
    task_id = store.submit_text_evaluation(transcript)
    return TaskSubmitResponse(task_id=task_id, status=TaskStatus.PENDING)
