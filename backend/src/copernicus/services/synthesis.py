"""音频重塑：转写按说话人合并 →（可选）LLM 口语改写 → ChatTTS 合成 → MP3。

合成在后台协程里运行，本服务持有这些协程的引用（asyncio 只对任务保持弱引用，
不保存会被回收）并在服务关停时取消它们。
"""

import asyncio
import logging
import os
import tempfile
import time
from pathlib import Path

import soundfile as sf

import copernicus.services.tts as tts
from copernicus.config import Settings
from copernicus.exceptions import TaskBusyError
from copernicus.schemas.transcription import TranscriptResponse
from copernicus.services.llm import LLMClient, OllamaClient
from copernicus.services.model_manager import ModelManager
from copernicus.services.task_store import TaskStore

logger = logging.getLogger(__name__)

_MIN_REWRITE_CHARS = 12  # 过短的块改写没有意义，且 LLM 容易画蛇添足

_STYLE_BY_ENERGY: tuple[tuple[int, str], ...] = (
    (2, "语气平静沉稳，娓娓道来，适合正式汇报或纪录片旁白。"),
    (5, '语气自然，口语化，像朋友间的日常对话。可加"嗯""那""其实""然后"等口语词。'),
    (7, "语气热情积极，有感染力，适当强调重点词，节奏明快。"),
)

_LIVESTREAM_STYLE = (
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


def build_rewrite_prompt(text: str, energy_level: int) -> str:
    style = next((s for limit, s in _STYLE_BY_ENERGY if energy_level <= limit), _LIVESTREAM_STYLE)
    return (
        "将下面这段话改写为适合真人朗读播出的口语表达。\n"
        f"风格要求：{style}\n"
        "保留核心意思，不要遗漏关键信息，直接输出改写结果，不要解释。\n\n"
        f"原文：{text}"
    )


class SynthesisService:
    def __init__(self, store: TaskStore, model_manager: ModelManager, settings: Settings) -> None:
        self._store = store
        self._models = model_manager
        self._settings = settings
        self._params = tts.SynthesisParams.from_settings(settings)
        self._handles: set[asyncio.Task] = set()

    async def start(
        self,
        task_id: str,
        transcript: TranscriptResponse,
        voice_override: dict[str, str] | None = None,
    ) -> None:
        """登记合成任务并在后台启动。同一任务已有合成在进行时抛出 TaskBusyError。"""
        if not self._store.start_synthesis(task_id):
            raise TaskBusyError("Synthesis already in progress for this task")

        # 登记之后的准备工作（含可能耗时数秒的 LLM 改写）一旦失败，必须把任务标为失败，
        # 否则它会永远停在 running：后续提交返回 409，任务也无法删除
        try:
            voice_map = tts.build_voice_map(
                [e.speaker for e in transcript.transcript],
                self._settings.tts_default_voices,
                override=voice_override,
            )
            chunks = tts.merge_by_speaker(transcript.transcript)
            if self._settings.tts_rewrite_enabled and chunks:
                chunks = await self._rewrite(chunks)
        except BaseException as exc:
            self._store.fail_synthesis(task_id, str(exc) or type(exc).__name__)
            raise

        handle = asyncio.create_task(self._run(task_id, chunks, voice_map))
        self._handles.add(handle)
        handle.add_done_callback(self._handles.discard)

    async def cancel_all(self) -> None:
        handles = list(self._handles)
        for handle in handles:
            handle.cancel()
        await asyncio.gather(*handles, return_exceptions=True)

    # -- 口语改写 ------------------------------------------------------------

    async def _rewrite(self, chunks: list[tuple[str, str]]) -> list[tuple[str, str]]:
        logger.info("Rewriting %d chunks for natural speech ...", len(chunks))
        started = time.perf_counter()
        llm = OllamaClient.for_rewrite(self._settings)
        try:
            # LLMClient 内置并发信号量，这里直接全部并发提交
            rewritten = await asyncio.gather(*[self._rewrite_chunk(s, t, llm) for s, t in chunks])
        finally:
            await llm.close()
        logger.info("Rewrite done in %.1fs", time.perf_counter() - started)
        return list(rewritten)

    async def _rewrite_chunk(self, speaker: str, text: str, llm: LLMClient) -> tuple[str, str]:
        """用 LLM 把单个文本块改写为口语化表达，失败时回退原文。"""
        if len(text) < _MIN_REWRITE_CHARS:
            return speaker, text
        try:
            resp = await llm.chat(
                [{"role": "user", "content": build_rewrite_prompt(text, self._settings.tts_energy_level)}],
                temperature=0.75,
                num_ctx=self._settings.tts_rewrite_num_ctx,
                think=False,
                num_predict=300,
            )
        except Exception as exc:
            logger.warning("Rewrite failed for chunk (fallback to original): %s", exc)
            return speaker, text
        rewritten = resp.content.strip()
        if not rewritten:
            return speaker, text
        logger.debug("[rewrite][%s]\n  原文: %s\n  改写: %s", speaker, text, rewritten)
        return speaker, rewritten

    # -- 合成 ------------------------------------------------------------------

    async def _run(self, task_id: str, chunks: list[tuple[str, str]], voice_map: dict[str, str]) -> None:
        output = self._store.persistence.path_of(task_id) / "synthesis.mp3"
        partial = output.with_suffix(".partial.mp3")  # 先写临时文件再改名：失败不会留下残缺的 mp3
        started = time.perf_counter()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                # exclusive：先卸载 ASR 腾出显存；unload_after：合成是偶发操作，
                # 用完立即释放约 4GB，否则它会与后续的 ASR/LLM 同时驻留
                async with self._models.use("tts", exclusive=True, unload_after=True) as model:
                    parts = await asyncio.to_thread(
                        tts.synthesize_chunks_batched, chunks, model, voice_map, self._params, Path(tmp)
                    )
                if not parts:
                    self._store.fail_synthesis(task_id, "Synthesis produced no audio")
                    return

                synthesis_ms = round((time.perf_counter() - started) * 1000, 1)
                duration_ms = round(sum(sf.info(str(p)).duration * 1000 for p in parts), 1)
                await tts.concat_parts_to_mp3(parts, partial)
                os.replace(partial, output)

            self._store.persistence.save_data(
                task_id, "synthesis_result.json",
                {"duration_ms": duration_ms, "synthesis_time_ms": synthesis_ms},
            )
            self._store.finish_synthesis(task_id, duration_ms, synthesis_ms)
            logger.info("Synthesis completed for task %s (%.1fs)", task_id, synthesis_ms / 1000)
        except asyncio.CancelledError:
            self._store.fail_synthesis(task_id, "服务关停，合成已中断")
            raise
        except Exception as exc:
            logger.error("Synthesis failed for task %s: %s", task_id, exc, exc_info=True)
            self._store.fail_synthesis(task_id, str(exc) or type(exc).__name__)
        finally:
            partial.unlink(missing_ok=True)
