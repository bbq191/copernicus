import json
import re

from fastapi import APIRouter, Depends, Form, HTTPException, Request

from copernicus.dependencies import get_task_store, get_template_manager
from copernicus.schemas.task import TaskStatus, TaskSubmitResponse
from copernicus.services.task_store import TaskStore
from copernicus.services.template_manager import TemplateManager

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


@router.get(
    "/templates",
    summary="获取所有可用纪要模板",
    tags=["系统"],
)
async def list_templates(
    tm: TemplateManager = Depends(get_template_manager),
) -> list[dict]:
    """返回所有已加载纪要模板的元数据列表（id / name / description）。

    API 调用方在提交评估任务前，可先调用此接口获取合法的 `template_id`。
    """
    return tm.get_all_metadata()


@router.post(
    "/templates/reload",
    summary="热重载纪要模板",
    tags=["系统"],
)
async def reload_templates(
    tm: TemplateManager = Depends(get_template_manager),
) -> dict:
    """重新扫描 templates/ 目录，将最新的模板内容加载到内存，无需重启服务。

    正在运行的推理任务不受影响：重载在当前 asyncio 事件循环的空闲时隙执行，
    读取完成后原子替换内存字典，并发请求始终能读到完整的模板数据。
    """
    count = tm.reload()
    return {"reloaded": count, "templates": tm.get_all_metadata()}


@router.post(
    "/evaluate/text/async",
    response_model=TaskSubmitResponse,
    status_code=202,
    summary="提交纯文本评估任务",
)
async def submit_text_evaluation_task(
    text: str = Form(...),
    template_id: str = Form(default="universal"),
    parent_task_id: str | None = Form(default=None),
    store: TaskStore = Depends(get_task_store),
) -> TaskSubmitResponse:
    """对已有文本执行 Map-Reduce 评估，按指定模板生成会议纪要。

    `template_id` 可选，默认使用通用模版（`universal`）。传入非法 `template_id`
    时自动 fallback 到通用模版，不返回错误。

    `parent_task_id` 可选，填写后评估结果将写入对应任务的
    `evaluation.json`，供 `GET /tasks/{task_id}/results` 返回。
    """
    if not text.strip():
        raise HTTPException(status_code=422, detail="Text must not be empty")
    if len(text.encode()) > 500 * 1024:
        raise HTTPException(status_code=413, detail="Text too large (max 500 KB)")
    task_id = store.submit_text_evaluation(
        text, template_id=template_id, parent_task_id=parent_task_id
    )
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
    """接收第三方 ASR 转写结果，提取正文后按通用模版生成会议纪要。

    直接接受原始请求体（`text/plain`），支持两种格式：

    - **第三方格式**：`[时间戳]{JSON}`，自动提取 JSON 中的 `content` 字段。
    - **纯文本**：直接作为转写内容处理。

    如需指定模板，请改用 `POST /evaluate/text/async`。
    """
    body = await request.body()
    if len(body) > 500 * 1024:
        raise HTTPException(status_code=413, detail="Request body too large (max 500 KB)")
    raw = body.decode("utf-8")
    transcript = _extract_transcript(raw)
    if not transcript.strip():
        raise HTTPException(status_code=422, detail="Text must not be empty")
    task_id = store.submit_text_evaluation(transcript, template_id="universal")
    return TaskSubmitResponse(task_id=task_id, status=TaskStatus.PENDING)
