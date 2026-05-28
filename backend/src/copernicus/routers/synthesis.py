import asyncio
import logging
import tempfile
import time
from pathlib import Path

import soundfile as sf
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from copernicus.config import settings
from copernicus.dependencies import get_model_manager, get_task_store
from copernicus.schemas.synthesis import SynthesisRequest, SynthesisStatusResponse
from copernicus.schemas.transcription import TranscriptResponse
from copernicus.services.llm import OllamaClient
from copernicus.services.model_manager import ModelManager
from copernicus.services.task_store import LLM_ACTIVE_STATUSES, TaskStore
import copernicus.services.tts as tts_service

logger = logging.getLogger(__name__)


def _build_rewrite_prompt(text: str, energy_level: int) -> str:
    if energy_level <= 2:
        style = "语气平静沉稳，娓娓道来，适合正式汇报或纪录片旁白。"
        extra = ""
    elif energy_level <= 5:
        style = '语气自然，口语化，像朋友间的日常对话。可加"嗯""那""其实""然后"等口语词。'
        extra = ""
    elif energy_level <= 7:
        style = "语气热情积极，有感染力，适当强调重点词，节奏明快。"
        extra = ""
    else:
        style = (
            "你是顶流带货主播，用极度亢奋的直播口播风格改写。\n"
            "标点规则（非常重要）：\n"
            "  用逗号代替感叹号，句末用句号收尾。\n"
            "  逗号会让 TTS 加速并升调，感叹号反而导致合成故障。\n"
            "  ❌ 错误：只要 99！只有一千单！给我抢！\n"
            "  ✅ 正确：只要 99，只有一千单了，给我抢。\n"
            "改写规则：\n"
            "  ① 开头是呼唤词：家人们，姐妹们，老铁们\n"
            "  ② 全程短句，每句不超过十五字\n"
            "  ③ 至少三处强化词：封顶低价，买到就是赚到，绝了，限时，手慢无，直接冲\n"
            "  ④ 结尾是催单句：直接拍，别犹豫，最后几单冲，不买后悔。\n"
            "禁止输出任何 [ ] 标签和 * ** 等符号，只输出纯中文文字。"
        )
        extra = ""
    return (
        f"将下面这段话改写为适合真人朗读播出的口语表达。\n"
        f"风格要求：{style}\n"
        f"{extra}"
        f"保留核心意思，不要遗漏关键信息，直接输出改写结果，不要解释。\n\n"
        f"原文：{text}"
    )

router = APIRouter(prefix="/api/v1", tags=["音频重塑"])


async def _rewrite_chunk(
    speaker: str,
    text: str,
    llm: OllamaClient,
    num_ctx: int,
    energy_level: int,
) -> tuple[str, str]:
    """用 LLM 将单个文本块改写为口语化表达，失败时回退原文。"""
    if len(text) < 12:
        return speaker, text
    try:
        resp = await llm.chat(
            [{"role": "user", "content": _build_rewrite_prompt(text, energy_level)}],
            temperature=0.75,
            num_ctx=num_ctx,
            think=False,
            num_predict=300,
        )
        rewritten = resp.content.strip()
        if rewritten:
            logger.info(
                "[rewrite][%s]\n  原文: %s\n  改写: %s",
                speaker, text, rewritten,
            )
            return speaker, rewritten
        return speaker, text
    except Exception as exc:
        logger.warning("Rewrite failed for chunk (fallback to original): %s", exc)
        return speaker, text


async def _rewrite_chunks(
    chunks: list[tuple[str, str]],
    llm: OllamaClient,
    num_ctx: int,
    energy_level: int,
) -> list[tuple[str, str]]:
    """并发改写所有 chunk，利用 OllamaClient 内置的并发信号量限流。"""
    results = await asyncio.gather(
        *[_rewrite_chunk(s, t, llm, num_ctx, energy_level) for s, t in chunks]
    )
    return list(results)


async def _run_synthesis(
    task_id: str,
    chunks: list[tuple[str, str]],
    voice_map: dict[str, str],
    store: TaskStore,
    model_manager: ModelManager,
) -> None:
    """后台协程：执行 TTS 合成并更新 job 状态。"""
    output_path = store.persistence.task_dir(task_id) / "synthesis.mp3"
    t0 = time.perf_counter()
    try:
        with tempfile.TemporaryDirectory() as tmp_work:
            work_dir = Path(tmp_work)

            async with model_manager.acquire("tts") as model:
                parts = await asyncio.to_thread(
                    tts_service.synthesize_chunks_batched,
                    chunks,
                    model,
                    voice_map,
                    settings.tts_pause_switch_speaker_ms,
                    settings.tts_synthesis_batch_chars,
                    work_dir,
                    settings.tts_max_sentence_chars,
                    settings.tts_oral_level,
                    settings.tts_break_level,
                    settings.tts_laugh_level,
                    settings.tts_energy_level,
                    settings.tts_temperature,
                    settings.tts_top_p,
                    settings.tts_top_k,
                    settings.tts_max_new_token,
                )

            if not parts:
                store.fail_synthesis(task_id, "Synthesis produced no audio")
                return

            synthesis_ms = round((time.perf_counter() - t0) * 1000, 1)
            duration_ms = round(sum(sf.info(str(p)).duration * 1000 for p in parts), 1)
            await tts_service.concat_parts_to_mp3(parts, output_path)

        store.persistence.save_dict(
            task_id, "synthesis_result.json",
            {"duration_ms": duration_ms, "synthesis_time_ms": synthesis_ms},
        )
        store.finish_synthesis(task_id, duration_ms, synthesis_ms)
        logger.info("Synthesis completed for task %s (%.1fs)", task_id, synthesis_ms / 1000)
    except Exception as exc:
        logger.error("Synthesis failed for task %s: %s", task_id, exc, exc_info=True)
        store.fail_synthesis(task_id, str(exc) or type(exc).__name__)


@router.post(
    "/tasks/{task_id}/synthesize",
    response_model=SynthesisStatusResponse,
    status_code=202,
    tags=["音频重塑"],
    summary="提交多说话人对话音频合成任务（异步）",
)
async def synthesize_task_audio(
    task_id: str,
    request: SynthesisRequest,
    store: TaskStore = Depends(get_task_store),
    model_manager: ModelManager | None = Depends(get_model_manager),
) -> SynthesisStatusResponse:
    """提交合成任务，立即返回 202；通过 GET /tasks/{task_id}/synthesis/status 轮询进度。

    - 不同说话人自动分配不同音色（可通过 `voice_map` 覆盖）。
    - 合成期间 ASR/LLM 模型自动卸载，独占显存；完成后驻留。
    - 同一任务重复提交时若合成正在进行则返回 409。
    """
    if model_manager is None:
        raise HTTPException(status_code=503, detail="ModelManager not available")

    active_llm = store.get_active_llm_task_ids()
    if active_llm:
        raise HTTPException(
            status_code=503,
            detail=f"LLM tasks in progress ({active_llm}), retry after they complete.",
        )

    transcript_data = store.persistence.load_json(task_id, "transcript.json")
    if transcript_data is None:
        raise HTTPException(status_code=404, detail="Transcript not found for task")

    transcript = TranscriptResponse.model_validate(transcript_data)
    if not transcript.transcript:
        raise HTTPException(status_code=422, detail="Transcript is empty")

    if not store.start_synthesis(task_id):
        raise HTTPException(status_code=409, detail="Synthesis already in progress for this task")

    speakers = [e.speaker for e in transcript.transcript]
    voice_map = tts_service.build_voice_map(
        speakers, settings.tts_default_voices, override=request.voice_map,
    )
    chunks = tts_service._merge_by_speaker(transcript.transcript)

    if settings.tts_rewrite_enabled and chunks:
        logger.info("Rewriting %d chunks for natural speech ...", len(chunks))
        t_rewrite = time.perf_counter()
        rewrite_llm = OllamaClient._make_rewrite_client(settings)
        try:
            chunks = await _rewrite_chunks(chunks, rewrite_llm, settings.tts_rewrite_num_ctx, settings.tts_energy_level)
        finally:
            await rewrite_llm.close()
        logger.info("Rewrite done in %.1fs", time.perf_counter() - t_rewrite)

    asyncio.create_task(_run_synthesis(task_id, chunks, voice_map, store, model_manager))
    return SynthesisStatusResponse(status="running")


@router.get(
    "/tasks/{task_id}/synthesis/status",
    response_model=SynthesisStatusResponse,
    tags=["音频重塑"],
    summary="查询合成任务状态",
)
async def get_synthesis_status(
    task_id: str,
    store: TaskStore = Depends(get_task_store),
) -> SynthesisStatusResponse:
    """轮询合成进度。status 取值：running | completed | failed。"""
    audio_url = f"/api/v1/tasks/{task_id}/synthesis"

    job = store.get_synthesis_job(task_id)
    if job is not None:
        if job.status == "completed":
            return SynthesisStatusResponse(
                status="completed",
                audio_url=audio_url,
                duration_ms=job.duration_ms,
                synthesis_time_ms=job.synthesis_time_ms,
            )
        if job.status == "failed":
            return SynthesisStatusResponse(status="failed", error=job.error)
        return SynthesisStatusResponse(status="running")

    # 服务重启后内存 job 丢失 — 从磁盘恢复
    result = store.persistence.load_json(task_id, "synthesis_result.json")
    if result:
        return SynthesisStatusResponse(
            status="completed",
            audio_url=audio_url,
            duration_ms=result.get("duration_ms"),
            synthesis_time_ms=result.get("synthesis_time_ms"),
        )

    mp3_path = store.persistence.task_dir(task_id) / "synthesis.mp3"
    if mp3_path.exists():
        return SynthesisStatusResponse(status="completed", audio_url=audio_url)

    raise HTTPException(status_code=404, detail="No synthesis found for this task")


@router.get(
    "/tasks/{task_id}/synthesis",
    tags=["音频重塑"],
    summary="下载已合成的对话音频",
)
async def get_synthesis_audio(
    task_id: str,
    store: TaskStore = Depends(get_task_store),
) -> FileResponse:
    """返回 `POST /synthesize` 生成的 MP3 文件。生命周期同原始媒体（24 小时后自动清理）。"""
    path = store.persistence.task_dir(task_id) / "synthesis.mp3"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Synthesis audio not found. Call POST /synthesize first.")
    return FileResponse(path, media_type="audio/mpeg", filename=f"{task_id}_synthesis.mp3")
