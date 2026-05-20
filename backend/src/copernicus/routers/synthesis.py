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
from copernicus.schemas.synthesis import SynthesisRequest, SynthesisResponse
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


@router.post(
    "/tasks/{task_id}/synthesize",
    response_model=SynthesisResponse,
    tags=["音频重塑"],
    summary="将转写结果合成为多说话人对话音频",
)
async def synthesize_task_audio(
    task_id: str,
    request: SynthesisRequest,
    store: TaskStore = Depends(get_task_store),
    model_manager: ModelManager | None = Depends(get_model_manager),
) -> SynthesisResponse:
    """基于任务的 `transcript.json` 生成多说话人有声对话，保存为 MP3。

    - 不同说话人自动分配不同音色（可通过 `voice_map` 覆盖）。
    - 连续相同说话人的段落合并后一次性送入 TTS，语调更自然。
    - 开启 `tts_rewrite_enabled` 后，合成前先用 LLM 将转写稿改写为自然口语。
    - 文本按批次合成，每批完成后清空 VRAM 缓存，防止长转写 OOM。
    - 合成前会通过 ModelManager 卸载 ASR/LLM，独占显存，完成后模型驻留
      等待下次请求，ASR 在下次转写时自动重载。
    - 可用音色（ChatTTS）：纯数字字符串直接作为 seed，其他字符串通过 MD5 映射，任意值均有效。
    """
    if model_manager is None:
        raise HTTPException(status_code=503, detail="ModelManager not available")

    # 若有 LLM 任务正在运行（Ollama 占用 VRAM），拒绝合成以避免 OOM
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

    speakers = [e.speaker for e in transcript.transcript]
    voice_map = tts_service.build_voice_map(
        speakers,
        settings.tts_default_voices,
        override=request.voice_map,
    )

    # 预合并 chunks（改写和 TTS 均基于此结构）
    chunks = tts_service._merge_by_speaker(transcript.transcript)

    # 口语改写（在 TTS acquire 之前完成，使用独立的本地 Ollama 客户端）
    if settings.tts_rewrite_enabled and chunks:
        logger.info("Rewriting %d chunks for natural speech ...", len(chunks))
        t_rewrite = time.perf_counter()
        rewrite_llm = OllamaClient._make_rewrite_client(settings)
        try:
            chunks = await _rewrite_chunks(chunks, rewrite_llm, settings.tts_rewrite_num_ctx, settings.tts_energy_level)
        finally:
            await rewrite_llm.close()
        logger.info("Rewrite done in %.1fs", time.perf_counter() - t_rewrite)

    output_path = store.persistence.task_dir(task_id) / "synthesis.mp3"
    t0 = time.perf_counter()

    # 每次合成使用独立临时目录，防止并发请求写入同名 WAV 文件后互相 unlink
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
            raise HTTPException(status_code=422, detail="Synthesis produced no audio")

        synthesis_ms = (time.perf_counter() - t0) * 1000
        duration_ms = sum(sf.info(str(p)).duration * 1000 for p in parts)

        await tts_service.concat_parts_to_mp3(parts, output_path)
        # TemporaryDirectory 退出时自动清理所有 WAV 部分文件

    return SynthesisResponse(
        audio_url=f"/api/v1/tasks/{task_id}/synthesis",
        duration_ms=round(duration_ms, 1),
        synthesis_time_ms=round(synthesis_ms, 1),
    )


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
