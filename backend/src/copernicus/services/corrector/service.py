import asyncio
import json
import logging
import re

from copernicus.services.llm import OllamaClient
from copernicus.services.text_corrector import TextCorrectorService
from copernicus.services.hotword_replacer import HotwordReplacerService
from copernicus.config import Settings
from copernicus.utils.llm_parse import strip_think_tags
from copernicus.utils.text import chunk_text, merge_chunks
from copernicus.utils.types import ProgressCallback

from .preprocess import preprocess_text
from .prompts import SYSTEM_PROMPT, TRANSCRIPT_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


class CorrectorService:
    def __init__(
        self,
        client: OllamaClient,
        settings: Settings,
        text_corrector: TextCorrectorService | None = None,
        hotword_replacer: HotwordReplacerService | None = None,
    ) -> None:
        self._client = client
        self._model = settings.llm_model_name
        self._temperature = settings.llm_temperature
        self._chunk_size = settings.correction_chunk_size
        self._overlap = settings.correction_overlap
        self._max_concurrency = settings.correction_max_concurrency
        self._num_ctx = settings.ollama_num_ctx_correction
        self._text_corrector = text_corrector
        self._hotword_replacer = hotword_replacer

    async def is_reachable(self) -> bool:
        return await self._client.is_reachable()

    async def correct(
        self, raw_text: str, on_progress: ProgressCallback | None = None
    ) -> str:
        """Correct ASR text using LLM with concurrent chunk processing."""
        if not raw_text.strip():
            return raw_text

        chunks = chunk_text(raw_text, self._chunk_size, self._overlap)
        total = len(chunks)
        semaphore = asyncio.Semaphore(self._max_concurrency)
        completed = 0
        lock = asyncio.Lock()

        async def _process(index: int, chunk: str) -> str:
            nonlocal completed
            async with semaphore:
                logger.info("Correcting chunk %d/%d ...", index + 1, total)
                result = await self._correct_chunk(chunk)
                async with lock:
                    completed += 1
                    if on_progress:
                        on_progress(completed, total)
                return result

        tasks = [_process(i, chunk) for i, chunk in enumerate(chunks)]
        corrected_chunks = await asyncio.gather(*tasks)

        return merge_chunks(list(corrected_chunks), self._overlap)

    async def correct_segments(
        self,
        segments_text: list[str],
        on_progress: ProgressCallback | None = None,
    ) -> list[str]:
        """Correct a list of segment texts concurrently (no overlap merging)."""
        if not segments_text:
            return []

        total = len(segments_text)
        semaphore = asyncio.Semaphore(self._max_concurrency)
        completed = 0
        lock = asyncio.Lock()

        async def _process(index: int, text: str) -> str:
            nonlocal completed
            async with semaphore:
                logger.info("Correcting segment %d/%d ...", index + 1, total)
                result = await self._correct_chunk(text)
                async with lock:
                    completed += 1
                    if on_progress:
                        on_progress(completed, total)
                return result

        tasks = [_process(i, text) for i, text in enumerate(segments_text)]
        return list(await asyncio.gather(*tasks))

    async def correct_transcript(
        self,
        entries: list[dict],
        batch_size: int = 15,
        on_progress: ProgressCallback | None = None,
    ) -> dict[int, str]:
        """四阶段纠正 transcript entries

        阶段 1：规则预处理（噪声过滤、重复词合并、数字规范化）
        阶段 2：热词强制替换（FlashText 多模式匹配）
        阶段 3：pycorrector/MacBERT 轻量级纠错（同音字/形近字）
        阶段 4：LLM 润色（去口语 + 倒装 + 标点）

        Each entry is {"id": int, "text": str}. Returns a mapping of id -> corrected text.
        """
        if not entries:
            return {}

        # ============================================================
        # 阶段 1：规则预处理
        # ============================================================
        preprocessed_entries: list[dict] = []
        filtered_ids: set[int] = set()

        for entry in entries:
            entry_id = entry["id"]
            original_text = entry.get("text", "")
            cleaned = preprocess_text(original_text)

            if cleaned is None:
                filtered_ids.add(entry_id)
            elif cleaned != original_text.strip():
                preprocessed_entries.append({"id": entry_id, "text": cleaned})
            else:
                preprocessed_entries.append(entry)

        logger.info(
            "Phase 1 (rule-based): %d entries -> %d valid, %d filtered as noise",
            len(entries),
            len(preprocessed_entries),
            len(filtered_ids),
        )

        if not preprocessed_entries:
            return {entry["id"]: "" for entry in entries}

        # ============================================================
        # 阶段 2：热词强制替换（可选）
        # ============================================================
        if self._hotword_replacer is not None:
            preprocessed_entries = self._hotword_replacer.replace_entries(preprocessed_entries)

        # ============================================================
        # 阶段 3：pycorrector 轻量级纠错（可选）
        # ============================================================
        if self._text_corrector is not None:
            preprocessed_entries = self._text_corrector.correct_entries(preprocessed_entries)

        # ============================================================
        # 阶段 4：LLM 润色
        # ============================================================
        batches = self._create_transcript_batches(
            preprocessed_entries, batch_size, self._chunk_size
        )

        total = len(batches)
        logger.info(
            "Phase 4 (LLM): %d entries -> %d batches (max_entries=%d, max_chars=%d)",
            len(preprocessed_entries), total, batch_size, self._chunk_size
        )
        semaphore = asyncio.Semaphore(self._max_concurrency)
        completed = 0
        lock = asyncio.Lock()

        async def _process_batch(
            index: int, batch: list[dict]
        ) -> dict[int, str]:
            nonlocal completed
            async with semaphore:
                logger.info("Correcting transcript batch %d/%d ...", index + 1, total)
                result = await self._correct_transcript_batch(batch)
                async with lock:
                    completed += 1
                    if on_progress:
                        on_progress(completed, total)
                return result

        tasks = [_process_batch(i, batch) for i, batch in enumerate(batches)]
        batch_results = await asyncio.gather(*tasks)

        merged: dict[int, str] = {}
        for batch_result in batch_results:
            merged.update(batch_result)

        for entry_id in filtered_ids:
            merged[entry_id] = ""

        return merged

    @staticmethod
    def _create_transcript_batches(
        entries: list[dict],
        max_entries: int = 15,
        max_chars: int = 800,
    ) -> list[list[dict]]:
        """创建同时满足条目数和字符数限制的批次"""
        batches: list[list[dict]] = []
        current_batch: list[dict] = []
        current_chars = 0

        for entry in entries:
            entry_chars = len(entry.get("text", ""))

            if entry_chars > max_chars:
                if current_batch:
                    batches.append(current_batch)
                    current_batch = []
                    current_chars = 0
                batches.append([entry])
                continue

            would_exceed_entries = len(current_batch) >= max_entries
            would_exceed_chars = current_chars + entry_chars > max_chars

            if current_batch and (would_exceed_entries or would_exceed_chars):
                batches.append(current_batch)
                current_batch = []
                current_chars = 0

            current_batch.append(entry)
            current_chars += entry_chars

        if current_batch:
            batches.append(current_batch)

        return batches

    async def _correct_transcript_batch(self, batch: list[dict]) -> dict[int, str]:
        """Send a batch of transcript entries to LLM for JSON-to-JSON correction."""
        fallback = {item["id"]: item["text"] for item in batch}
        batch_chars = sum(len(item.get("text", "")) for item in batch)
        batch_ids = [item["id"] for item in batch]

        try:
            input_json = json.dumps({"entries": batch}, ensure_ascii=False)
            logger.debug(
                "Batch ids=%s, entries=%d, chars=%d",
                batch_ids[:3] if len(batch_ids) > 3 else batch_ids,
                len(batch),
                batch_chars,
            )
            max_output_tokens = min(4096, batch_chars * 2 + 1024)

            response = await self._client.chat(
                messages=[
                    {"role": "system", "content": TRANSCRIPT_SYSTEM_PROMPT},
                    {"role": "user", "content": input_json},
                ],
                num_ctx=self._num_ctx,
                json_format=True,
                think=False,
                num_predict=max_output_tokens,
            )
            raw = response.content
            raw = strip_think_tags(raw).strip()

            if not raw:
                logger.warning("LLM returned empty response for transcript batch, using fallback")
                return fallback

            parsed = json.loads(raw)

            if isinstance(parsed, dict):
                entries_list = parsed.get("entries", [])
            elif isinstance(parsed, list):
                entries_list = parsed
            else:
                logger.warning("LLM transcript correction returned unexpected type, using fallback")
                return fallback

            result: dict[int, str] = {}
            for item in entries_list:
                if isinstance(item, dict) and "id" in item and "text" in item:
                    result[item["id"]] = item["text"]

            for entry_id, original_text in fallback.items():
                if entry_id not in result:
                    result[entry_id] = original_text

            return result
        except json.JSONDecodeError as e:
            logger.warning(
                "LLM transcript JSON parse failed, trying regex fallback: %s", e
            )
            return self._extract_entries_by_regex(raw, fallback)
        except Exception as e:
            logger.warning(
                "LLM transcript correction failed for batch (ids=%s, entries=%d, chars=%d): [%s] %s",
                batch_ids[:3] if len(batch_ids) > 3 else batch_ids,
                len(batch),
                batch_chars,
                type(e).__name__,
                e or "(no message)",
            )
            return fallback

    @staticmethod
    def _extract_entries_by_regex(
        raw: str, fallback: dict[int, str]
    ) -> dict[int, str]:
        """Last-resort extraction: find id/text pairs via regex when JSON parse fails."""
        pattern = re.compile(
            r'"id"\s*:\s*(\d+)\s*,\s*"text"\s*:\s*"((?:[^"\\]|\\.)*)"'
        )
        result: dict[int, str] = {}
        for m in pattern.finditer(raw):
            entry_id = int(m.group(1))
            text = m.group(2).replace('\\"', '"').replace("\\n", "\n")
            result[entry_id] = text

        if result:
            logger.info("Regex fallback recovered %d/%d entries", len(result), len(fallback))
            for entry_id, original_text in fallback.items():
                if entry_id not in result:
                    result[entry_id] = original_text
            return result

        logger.warning("Regex fallback also failed, using original text")
        return fallback

    async def _correct_chunk(self, text: str) -> str:
        """Send a single chunk to the LLM for correction."""
        try:
            response = await self._client.chat(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"待修正文本：\n{text}"},
                ],
                num_ctx=self._num_ctx,
            )
            content = response.content
            return strip_think_tags(content).strip() or text
        except Exception as e:
            logger.warning(
                "LLM correction failed for chunk, using raw text: [%s] %s",
                type(e).__name__,
                e or "(no message)",
            )
            return text
