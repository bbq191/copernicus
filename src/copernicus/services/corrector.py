import logging
from collections.abc import Callable

from openai import AsyncOpenAI

from copernicus.config import Settings
from copernicus.utils.text import chunk_text, merge_chunks

ProgressCallback = Callable[[int, int], None]

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
你是一个专业的中文ASR（语音转文字）后处理专家。
任务：接收一段ASR生成的原始文本，纠正其中的同音字错误、标点错误和明显的语法错误。
约束条件：
1. 严禁重写句子结构或删减内容，必须保持原意。
2. 严禁把口语词汇（如"那个"、"呃"）过度书面化，除非严重影响阅读。
3. 仅输出修正后的文本，不要输出任何解释。"""


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

    async def correct(
        self, raw_text: str, on_progress: ProgressCallback | None = None
    ) -> str:
        """Correct ASR text using LLM. Falls back to raw text on failure."""
        if not raw_text.strip():
            return raw_text

        chunks = chunk_text(raw_text, self._chunk_size, self._overlap)

        corrected_chunks = []
        for i, chunk in enumerate(chunks, 1):
            logger.info("Correcting chunk %d/%d ...", i, len(chunks))
            if on_progress:
                on_progress(i, len(chunks))
            result = await self._correct_chunk(chunk)
            corrected_chunks.append(result)

        return merge_chunks(corrected_chunks, self._overlap)

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
            return response.choices[0].message.content or text
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
