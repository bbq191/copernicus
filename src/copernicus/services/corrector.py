import asyncio
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
