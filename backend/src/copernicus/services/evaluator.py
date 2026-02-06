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
import re
from collections.abc import Callable

from copernicus.config import Settings
from copernicus.schemas.evaluation import EvaluationResult
from copernicus.services.llm import OllamaClient
from copernicus.utils.text import chunk_text

# (current_step, total_steps) — Map chunk 完成时 current 递增，Reduce 时 = total
ProgressCallback = Callable[[int, int], None]

logger = logging.getLogger(__name__)

# 单次直接评估 & Reduce 阶段共用的 JSON 输出 prompt
_EVALUATION_SYSTEM_PROMPT = """\
你是一个严格的数据提取引擎，不是聊天助手。
任务：根据用户输入的转写文本，提取关键评估指标。

### 评分维度 (满分 100 分)
请基于以下 3 个维度进行打分：
1. 逻辑连贯性 (35分)：开场、正文、结尾是否清晰，观点是否连贯。
2. 信息密度 (35分)：是否输出了有价值的干货（如数据、案例、论据），内容是否充实。
3. 表达清晰度 (30分)：语言是否清晰易懂，是否有歧义或冗余。

### 绝对格式约束
1. 你必须且只能输出一段合法的 JSON 字符串。
2. 严禁输出任何 Markdown 标记、开场白、结束语或解释文字。
3. 忽略 ASR 转写产生的轻微同音字错误，关注语义本身。
4. 如果无法提取某些字段，请填空字符串或 0。

### JSON 输出结构
{
    "meta": {
        "title": "拟定一个精准的标题",
        "category": "推测内容分类(如: 宏观经济/科技/企业培训/产品介绍)",
        "keywords": ["关键词1", "关键词2", "关键词3"]
    },
    "scores": {
        "logic": 0,
        "info_density": 0,
        "expression": 0,
        "total": 0
    },
    "analysis": {
        "main_points": ["核心观点1", "核心观点2", "核心观点3"],
        "key_data": ["提及的关键数据1", "提及的关键数据2"],
        "sentiment": "整体情感倾向(积极/中立/消极)"
    },
    "summary": "300字以内的深度摘要"
}"""

# Map 阶段：每个分段提取要点（非 JSON，纯文本输出，速度快）
_MAP_SYSTEM_PROMPT = """\
你是一个专业的内容分析助手。
任务：阅读给定的文本片段，提炼核心内容。

要求：
1. 提取该片段的核心观点（2-5 条）。
2. 提取提到的关键数据或事实（如有）。
3. 简要概括该片段的主题（1-2 句话）。
4. 不要写开场白或结束语，直接输出要点。
5. 忽略 ASR 转写的轻微同音字错误，关注语义。"""


class EvaluatorService:
    def __init__(self, client: OllamaClient, settings: Settings) -> None:
        self._client = client
        self._max_text_chars = settings.evaluation_max_text_chars
        self._chunk_size = settings.evaluation_chunk_size
        self._num_ctx = settings.evaluation_num_ctx

    async def evaluate(
        self,
        text: str,
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
            # 短文本：直接评估，总步骤 = 1
            if on_progress:
                on_progress(0, 1)
            result = await self._evaluate_direct(text, max_retries=max_retries)
            if on_progress:
                on_progress(1, 1)
            return result

        return await self._evaluate_map_reduce(
            text, max_retries=max_retries, on_progress=on_progress
        )

    # ------------------------------------------------------------------ #
    #  短文本：直接单次评估
    # ------------------------------------------------------------------ #

    async def _evaluate_direct(
        self, text: str, *, max_retries: int = 2
    ) -> EvaluationResult:
        logger.info("Direct evaluation: %d chars", len(text))
        return await self._call_evaluation_llm(text, max_retries=max_retries)

    # ------------------------------------------------------------------ #
    #  长文本：Map-Reduce
    # ------------------------------------------------------------------ #

    async def _evaluate_map_reduce(
        self,
        text: str,
        *,
        max_retries: int = 2,
        on_progress: ProgressCallback | None = None,
    ) -> EvaluationResult:
        chunks = chunk_text(text, self._chunk_size, overlap=0)
        total_steps = len(chunks) + 1  # map chunks + reduce
        logger.info(
            "Map-Reduce evaluation: %d chars -> %d chunks (chunk_size=%d)",
            len(text),
            len(chunks),
            self._chunk_size,
        )
        if on_progress:
            on_progress(0, total_steps)

        # Map：并发提取每个分段的要点，每完成一个报告进度
        completed = 0
        lock = asyncio.Lock()

        async def _map_with_progress(i: int, chunk: str) -> str:
            nonlocal completed
            result = await self._map_chunk(i, chunk, len(chunks))
            async with lock:
                completed += 1
                if on_progress:
                    on_progress(completed, total_steps)
            return result

        map_tasks = [
            _map_with_progress(i, chunk) for i, chunk in enumerate(chunks)
        ]
        summaries = await asyncio.gather(*map_tasks)

        # Reduce：合并所有分段要点，生成最终 JSON
        combined = "\n\n---\n\n".join(
            f"【片段 {i + 1}/{len(chunks)}】\n{s}" for i, s in enumerate(summaries)
        )
        logger.info(
            "Map phase done, combined summary: %d chars. Starting reduce...",
            len(combined),
        )
        result = await self._reduce(combined, max_retries=max_retries)
        if on_progress:
            on_progress(total_steps, total_steps)
        return result

    async def _map_chunk(self, index: int, chunk: str, total: int) -> str:
        """Map 阶段：提取单个分段的要点。"""
        logger.info("Map chunk %d/%d (%d chars)...", index + 1, total, len(chunk))
        try:
            response = await self._client.chat(
                messages=[
                    {"role": "system", "content": _MAP_SYSTEM_PROMPT},
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
                num_predict=1024,
            )
            content = _strip_think_tags(response.content).strip()
            logger.info("Map chunk %d/%d done: %d chars", index + 1, total, len(content))
            return content or f"（片段 {index + 1} 无法提取要点）"
        except Exception as e:
            logger.warning("Map chunk %d/%d failed: %s", index + 1, total, e)
            # fallback：截取原文前 500 字作为摘要
            return chunk[:500]

    async def _reduce(
        self, combined_summary: str, *, max_retries: int = 2
    ) -> EvaluationResult:
        """Reduce 阶段：基于所有分段要点生成最终评估 JSON。"""
        reduce_text = (
            "以下是一篇长文的分段要点合集。"
            "请综合这些要点，对原文整体进行评估并生成最终报告。\n\n"
            f"{combined_summary}"
        )
        return await self._call_evaluation_llm(reduce_text, max_retries=max_retries)

    # ------------------------------------------------------------------ #
    #  共用：调用 LLM 生成评估 JSON
    # ------------------------------------------------------------------ #

    async def _call_evaluation_llm(
        self, text: str, *, max_retries: int = 2
    ) -> EvaluationResult:
        last_error: Exception | None = None

        for attempt in range(1, max_retries + 1):
            messages: list[dict[str, str]] = [
                {"role": "system", "content": _EVALUATION_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"【待分析文本开始】\n{text}\n【待分析文本结束】\n\n"
                        "再次提醒：请忽略文本中的口语化表达，仅输出 JSON 格式的评估报告。"
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
            content = _extract_json(raw)

            try:
                data = json.loads(content)
                result = EvaluationResult(**data)
                logger.info(
                    "Evaluation succeeded on attempt %d/%d: title=%s, total_score=%s",
                    attempt,
                    max_retries,
                    result.meta.title,
                    result.scores.total,
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
        raise last_error  # type: ignore[misc]


_THINK_PAIR_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_THINK_OPEN_RE = re.compile(r"<think>.*", re.DOTALL)
_THINK_CLOSE_RE = re.compile(r"^.*?</think>", re.DOTALL)


def _strip_think_tags(text: str) -> str:
    """Remove <think>...</think> tags from LLM output."""
    text = _THINK_PAIR_RE.sub("", text)
    text = _THINK_OPEN_RE.sub("", text)
    text = _THINK_CLOSE_RE.sub("", text)
    return text


def _extract_json(text: str) -> str:
    """Extract JSON from LLM output, stripping think tags and markdown fences."""
    text = _strip_think_tags(text)
    text = text.replace("```json", "").replace("```", "").strip()
    idx = text.find("{")
    if idx > 0:
        text = text[idx:]
    last = text.rfind("}")
    if last >= 0:
        text = text[: last + 1]
    return text.strip()
