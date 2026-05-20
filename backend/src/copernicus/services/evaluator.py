"""Map-Reduce 评估服务

解决显存瓶颈：RTX 5080 Laptop 16GB 无法同时容纳模型权重(~9.5GB) + 大 KV Cache。
当输入 > 20k 字符时，KV Cache 会膨胀到 6-8GB，导致 VRAM Swap，推理速度从 40 t/s
暴跌至 1-2 t/s。

策略：
- 短文本 (< chunk_size)：直接单次评估
- 长文本：Map 阶段分段提取要点 -> Reduce 阶段合并生成最终 JSON
- 每次 LLM 调用的 num_ctx 控制在 8192，显存占用稳定在 ~12GB
"""

import asyncio
import json
import logging

from copernicus.config import Settings
from copernicus.schemas.evaluation import EvaluationResult
from copernicus.services.llm import OllamaClient
from copernicus.utils.llm_parse import extract_json_object, strip_think_tags
from copernicus.utils.text import chunk_text
from copernicus.utils.types import ProgressCallback

logger = logging.getLogger(__name__)


def build_map_prompt(template_prompt: str) -> str:
    return f"""你是一个专业的内容分析助手。
任务：阅读给定的文本片段，为最终的【目标模版】提取所有相关的核心素材。

【最终要生成的模版参考】
{template_prompt}

要求：
1. 仔细阅读模版要求，宁可多提取素材，绝不遗漏模版中可能需要的任何数据、观点或计划。
2. 忽略 ASR 转写的轻微同音字错误，关注语义。
3. 不要写开场白或结束语，直接列出提取的要点。"""


def build_reduce_prompt(template_prompt: str) -> str:
    return f"""你是一个严格的数据提取与排版引擎。
任务：根据用户输入的文本，严格按照以下【目标模版】生成会议纪要。

【目标模版与输出要求】
{template_prompt}

### 绝对格式约束
1. 你必须且只能输出一段合法的 JSON 字符串。
2. 将你按照模版排版好的完整 Markdown 文本全部放入 JSON 的 `formatted_content` 字段。
3. 另外提炼一个简短的会议标题放入 `title` 字段（不超过 20 字）。
4. 严禁输出任何开场白、结束语或多余的解释文字。

### 强制 JSON 输出结构
{{
    "formatted_content": "（严格按照上方【目标模版】要求排版的完整 Markdown 文本，格式完全由模版决定）",
    "title": "（不超过20字的会议主题标题）"
}}"""


class EvaluatorService:
    def __init__(self, client: OllamaClient, settings: Settings) -> None:
        self._client = client
        self._max_text_chars = settings.evaluation_max_text_chars
        self._chunk_size = settings.evaluation_chunk_size
        self._num_ctx = settings.evaluation_num_ctx

    async def evaluate(
        self,
        text: str,
        template_prompt: str,
        *,
        max_retries: int = 2,
        on_progress: ProgressCallback | None = None,
    ) -> EvaluationResult:
        """评估文本内容，长文本自动使用 Map-Reduce 策略。"""
        if len(text) > self._max_text_chars:
            logger.warning(
                "Text too long for evaluation (%d chars), truncating to %d chars",
                len(text),
                self._max_text_chars,
            )
            text = text[: self._max_text_chars]

        if len(text) <= self._chunk_size:
            if on_progress:
                on_progress(0, 1)
            result = await self._evaluate_direct(text, template_prompt, max_retries=max_retries)
            if on_progress:
                on_progress(1, 1)
            return result

        return await self._evaluate_map_reduce(
            text, template_prompt, max_retries=max_retries, on_progress=on_progress
        )

    # ------------------------------------------------------------------ #
    #  短文本：直接单次评估
    # ------------------------------------------------------------------ #

    async def _evaluate_direct(
        self, text: str, template_prompt: str, *, max_retries: int = 2
    ) -> EvaluationResult:
        logger.info("Direct evaluation: %d chars", len(text))
        return await self._call_evaluation_llm(text, template_prompt, max_retries=max_retries)

    # ------------------------------------------------------------------ #
    #  长文本：Map-Reduce
    # ------------------------------------------------------------------ #

    async def _evaluate_map_reduce(
        self,
        text: str,
        template_prompt: str,
        *,
        max_retries: int = 2,
        on_progress: ProgressCallback | None = None,
    ) -> EvaluationResult:
        chunks = chunk_text(text, self._chunk_size, overlap=0)
        total_steps = len(chunks) + 1
        logger.info(
            "Map-Reduce evaluation: %d chars -> %d chunks (chunk_size=%d)",
            len(text),
            len(chunks),
            self._chunk_size,
        )
        if on_progress:
            on_progress(0, total_steps)

        completed = 0
        lock = asyncio.Lock()

        async def _map_with_progress(i: int, chunk: str) -> str:
            nonlocal completed
            result = await self._map_chunk(i, chunk, len(chunks), template_prompt)
            async with lock:
                completed += 1
                if on_progress:
                    on_progress(completed, total_steps)
            return result

        map_tasks = [
            _map_with_progress(i, chunk) for i, chunk in enumerate(chunks)
        ]
        summaries = await asyncio.gather(*map_tasks)

        combined = "\n\n---\n\n".join(
            f"【片段 {i + 1}/{len(chunks)}】\n{s}" for i, s in enumerate(summaries)
        )
        logger.info(
            "Map phase done, combined summary: %d chars. Starting reduce...",
            len(combined),
        )
        result = await self._reduce(combined, template_prompt, max_retries=max_retries)
        if on_progress:
            on_progress(total_steps, total_steps)
        return result

    async def _map_chunk(
        self, index: int, chunk: str, total: int, template_prompt: str
    ) -> str:
        logger.info("Map chunk %d/%d (%d chars)...", index + 1, total, len(chunk))
        try:
            response = await self._client.chat(
                messages=[
                    {"role": "system", "content": build_map_prompt(template_prompt)},
                    {
                        "role": "user",
                        "content": (
                            f"以下是第 {index + 1}/{total} 个文本片段，"
                            f"请提炼核心要点：\n\n{chunk}"
                        ),
                    },
                ],
                num_ctx=self._num_ctx,
                think=False,
                num_predict=2048,
            )
            content = strip_think_tags(response.content).strip()
            logger.info("Map chunk %d/%d done: %d chars", index + 1, total, len(content))
            return content or f"（片段 {index + 1} 无法提取要点）"
        except Exception as e:
            logger.warning("Map chunk %d/%d failed: %s", index + 1, total, e)
            return chunk[:500]

    async def _reduce(
        self, combined_summary: str, template_prompt: str, *, max_retries: int = 2
    ) -> EvaluationResult:
        reduce_text = (
            "以下是一篇长文的分段要点合集。\n\n"
            f"{combined_summary}"
        )
        return await self._call_evaluation_llm(reduce_text, template_prompt, max_retries=max_retries)

    # ------------------------------------------------------------------ #
    #  共用：调用 LLM 生成评估 JSON
    # ------------------------------------------------------------------ #

    async def _call_evaluation_llm(
        self, text: str, template_prompt: str, *, max_retries: int = 2
    ) -> EvaluationResult:
        last_error: Exception | None = None

        for attempt in range(1, max_retries + 1):
            messages: list[dict[str, str]] = [
                {"role": "system", "content": build_reduce_prompt(template_prompt)},
                {
                    "role": "user",
                    "content": (
                        f"【待整理文本开始】\n{text}\n【待整理文本结束】\n\n"
                        "再次提醒：请严格按照模版排版，仅输出 JSON 格式结果。"
                    ),
                },
            ]
            if attempt > 1:
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "你上次的回答不是合法JSON。"
                            "请严格只输出JSON，不要输出任何思考过程、Markdown或解释文字。"
                        ),
                    }
                )

            response = await self._client.chat(
                messages=messages,
                json_format=True,
                num_ctx=self._num_ctx,
                num_predict=4096,
            )
            raw = response.content
            content = extract_json_object(raw)

            try:
                data = json.loads(content)
                result = EvaluationResult(**data)
                logger.info(
                    "Evaluation succeeded on attempt %d/%d: title=%s",
                    attempt,
                    max_retries,
                    result.title,
                )
                return result
            except (json.JSONDecodeError, Exception) as e:
                last_error = e
                logger.warning(
                    "Evaluate attempt %d/%d failed: %s | extracted: %s",
                    attempt,
                    max_retries,
                    e,
                    content[:150],
                )

        logger.error("All %d evaluate attempts failed", max_retries)
        raise last_error or RuntimeError("All evaluate attempts failed")
