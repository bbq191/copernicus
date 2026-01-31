import asyncio
import json
import logging
import re
from collections.abc import Callable

from openai import AsyncOpenAI

from copernicus.config import Settings
from copernicus.utils.text import chunk_text, merge_chunks

_THINK_RE = re.compile(
    r"<think>.*?</think>"
    r"|<think>.*"
    r"|^.*?</think>",
    re.DOTALL,
)

_JSON_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)

ProgressCallback = Callable[[int, int], None]

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
你是一个专业的文本校对工具。
任务：接收ASR语音转写文本，输出修正后的文本。
要求：
1. 仅输出修正后的正文，严禁输出任何开场白、解释、修正列表或Markdown标记。
2. 修正同音字错误（如"受权"->"授权"）。
3. 修正标点符号，使其符合阅读习惯。
4. 保持原句意，不要重写或删减内容。
5. 如果文本包含无法确定的口语，保留原样。"""

TRANSCRIPT_SYSTEM_PROMPT = """\
你是一个字幕校对专家。
输入是一个包含句子ID和原始内容的JSON数组。
任务：修正每个对象中 text 字段的错别字、标点符号，并轻度去除口语冗余。

规则：
1. 绝对严禁修改 id 字段。
2. 绝对严禁合并或拆分句子。
3. 修正同音字错误（如"惊济"->"经济"，"特朗谱"->"特朗普"）。
4. 修正阿拉伯数字格式（如"二零二五"->"2025"）。
5. 修正标点符号，使其符合阅读习惯。
6. 去除无意义的重复口语（如"那个那个"->"那个"，"终于终于终于"->"终于"），但保持句子原意。
7. 保持原句意，不要重写或大幅删减内容。
8. 仅输出合法的JSON数组，严禁输出任何开场白、解释或Markdown标记。

【输入示例】
[{"id": 1, "text": "二零二五全球惊济概览。"}, {"id": 2, "text": "终于终于终于特朗谱把关税旋风刮到全球。"}]

【输出示例】
[{"id": 1, "text": "2025全球经济概览。"}, {"id": 2, "text": "终于，特朗普把关税旋风刮到全球。"}]"""


class CorrectorService:
    def __init__(self, settings: Settings) -> None:
        self._client = AsyncOpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            timeout=settings.llm_timeout,
        )
        self._model = settings.llm_model_name
        self._temperature = settings.llm_temperature
        self._chunk_size = settings.correction_chunk_size
        self._overlap = settings.correction_overlap
        self._max_concurrency = settings.correction_max_concurrency

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

        async def _process(index: int, chunk: str) -> str:
            nonlocal completed
            async with semaphore:
                logger.info("Correcting chunk %d/%d ...", index + 1, total)
                result = await self._correct_chunk(chunk)
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

        async def _process(index: int, text: str) -> str:
            nonlocal completed
            async with semaphore:
                logger.info("Correcting segment %d/%d ...", index + 1, total)
                result = await self._correct_chunk(text)
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
        """Correct transcript entries using JSON-to-JSON approach.

        Each entry is {"id": int, "text": str}. Returns a mapping of id -> corrected text.
        """
        if not entries:
            return {}

        batches: list[list[dict]] = []
        for i in range(0, len(entries), batch_size):
            batches.append(entries[i : i + batch_size])

        total = len(batches)
        semaphore = asyncio.Semaphore(self._max_concurrency)
        completed = 0

        async def _process_batch(
            index: int, batch: list[dict]
        ) -> dict[int, str]:
            nonlocal completed
            async with semaphore:
                logger.info("Correcting transcript batch %d/%d ...", index + 1, total)
                result = await self._correct_transcript_batch(batch)
                completed += 1
                if on_progress:
                    on_progress(completed, total)
                return result

        tasks = [_process_batch(i, batch) for i, batch in enumerate(batches)]
        batch_results = await asyncio.gather(*tasks)

        merged: dict[int, str] = {}
        for batch_result in batch_results:
            merged.update(batch_result)

        return merged

    async def _correct_transcript_batch(self, batch: list[dict]) -> dict[int, str]:
        """Send a batch of transcript entries to LLM for JSON-to-JSON correction."""
        fallback = {item["id"]: item["text"] for item in batch}
        try:
            input_json = json.dumps(batch, ensure_ascii=False)
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": TRANSCRIPT_SYSTEM_PROMPT},
                    {"role": "user", "content": input_json},
                ],
                temperature=self._temperature,
            )
            raw = response.choices[0].message.content or ""
            raw = _THINK_RE.sub("", raw).strip()
            raw = raw.replace("```json", "").replace("```", "").strip()

            # Extract the outermost JSON array if LLM added extra text
            if raw and raw[0] != "[":
                match = _JSON_ARRAY_RE.search(raw)
                if match:
                    raw = match.group(0)

            if not raw:
                logger.warning("LLM returned empty response for transcript batch, using fallback")
                return fallback

            parsed = json.loads(raw)
            if not isinstance(parsed, list):
                logger.warning("LLM transcript correction returned non-list, using fallback")
                return fallback

            result: dict[int, str] = {}
            for item in parsed:
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
                "LLM transcript correction failed for batch, using fallback: %s", e
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
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"待修正文本：\n{text}"},
                ],
                temperature=self._temperature,
            )
            content = response.choices[0].message.content or text
            return _THINK_RE.sub("", content).strip() or text
        except Exception as e:
            logger.warning("LLM correction failed for chunk, using raw text: %s", e)
            return text

    async def is_reachable(self) -> bool:
        """Check if the LLM API is reachable."""
        try:
            await self._client.models.list()
            return True
        except Exception:
            return False
