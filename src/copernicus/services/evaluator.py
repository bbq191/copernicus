import json
import logging
import re

from openai import AsyncOpenAI

from copernicus.config import Settings
from copernicus.schemas.evaluation import EvaluationResult

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
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


class EvaluatorService:
    def __init__(self, settings: Settings) -> None:
        self._client = AsyncOpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            timeout=settings.llm_timeout,
        )
        self._model = settings.llm_model_name
        self._temperature = settings.llm_temperature
        self._max_text_chars = settings.evaluation_max_text_chars

    async def evaluate(self, text: str, *, max_retries: int = 2) -> EvaluationResult:
        """Evaluate text content and return structured analysis."""
        if len(text) > self._max_text_chars:
            logger.warning(
                "Text too long for evaluation (%d chars), truncating to %d chars",
                len(text),
                self._max_text_chars,
            )
            text = text[: self._max_text_chars]

        last_error: Exception | None = None

        for attempt in range(1, max_retries + 1):
            messages: list[dict[str, str]] = [
                {"role": "system", "content": SYSTEM_PROMPT},
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

            response = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                temperature=self._temperature,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content or ""
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


def _extract_json(text: str) -> str:
    """Extract JSON from LLM output, stripping think tags and markdown fences."""
    text = _THINK_PAIR_RE.sub("", text)
    text = _THINK_OPEN_RE.sub("", text)
    text = _THINK_CLOSE_RE.sub("", text)
    text = text.replace("```json", "").replace("```", "").strip()
    idx = text.find("{")
    if idx > 0:
        text = text[idx:]
    last = text.rfind("}")
    if last >= 0:
        text = text[: last + 1]
    return text.strip()
