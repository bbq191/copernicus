import asyncio
import json
import logging
import re
from collections.abc import Callable

from copernicus.services.llm import OllamaClient
from copernicus.services.text_corrector import TextCorrectorService
from copernicus.services.hotword_replacer import HotwordReplacerService
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


# ============================================================
# 阶段 1：规则预处理（快速过滤噪声和明显错误）
# ============================================================

# 纯噪声短语模式（英文 ASR 幻觉）
_NOISE_PHRASE_RE = re.compile(
    r"^\s*(?:the\s+)*(?:the|a|an|yeah|yes|no|ok|okay|um|uh|oh|ah|er|hmm|hm|mm)\s*[，。,.]?\s*$",
    re.IGNORECASE,
)

# 中文语气词
_NOISE_WORDS_CN = {"嗯", "啊", "哦", "呃", "唔", "嘿", "哈", "呵", "噢", "喔", "诶", "哎", "唉", "呀"}

# 重复词模式（如 "那个那个" -> "那个"）
_REPEAT_PATTERNS = [
    (re.compile(r"(那个){2,}"), "那个"),
    (re.compile(r"(这个){2,}"), "这个"),
    (re.compile(r"(就是){2,}"), "就是"),
    (re.compile(r"(然后){2,}"), "然后"),
    (re.compile(r"(所以){2,}"), "所以"),
    (re.compile(r"(但是){2,}"), "但是"),
    (re.compile(r"(因为){2,}"), "因为"),
    (re.compile(r"(可能){2,}"), "可能"),
    (re.compile(r"(应该){2,}"), "应该"),
    (re.compile(r"(终于){2,}"), "终于"),
    (re.compile(r"(了解){2,}"), "了解"),
    (re.compile(r"(不好意思){2,}"), "不好意思"),
    # 语气词重复
    (re.compile(r"(嗯){2,}"), "嗯"),
    (re.compile(r"(啊){2,}"), "啊"),
    (re.compile(r"(哦){2,}"), "哦"),
    (re.compile(r"(呃){2,}"), "呃"),
]

# 英文噪声前缀清理
_EN_NOISE_PREFIX_RE = re.compile(r"^\s*(?:the\s+)+", re.IGNORECASE)

# ============================================================
# 数字规范化：中文数字 -> 阿拉伯数字
# ============================================================
_CN_DIGIT_MAP = {
    "零": "0", "〇": "0", "一": "1", "二": "2", "三": "3",
    "四": "4", "五": "5", "六": "6", "七": "7", "八": "8", "九": "9",
}

# 年份模式：X零XX年 或 XXXX年（四位中文数字 + 年字）
_YEAR_RE = re.compile(
    r"([一二三四五六七八九])"
    r"([零〇])"
    r"([一二三四五六七八九零〇])"
    r"([一二三四五六七八九零〇])"
    r"(?=年)"
)

# 通用四位中文数字模式（如 "二零二五" 不跟 "年"，但在上下文中明显是年份）
_FOUR_DIGIT_CN_RE = re.compile(
    r"([一二三四五六七八九])"
    r"([零〇])"
    r"([一二三四五六七八九零〇])"
    r"([一二三四五六七八九零〇])"
)


def _cn_digits_to_arabic(match: re.Match) -> str:
    """将匹配到的四位中文数字转为阿拉伯数字"""
    return "".join(_CN_DIGIT_MAP.get(c, c) for c in match.group())


def preprocess_text(text: str) -> str | None:
    """阶段 1：规则预处理，快速清理噪声和明显错误

    Args:
        text: 原始文本

    Returns:
        清理后的文本，如果是纯噪声则返回 None
    """
    if not text or not text.strip():
        return None

    cleaned = text.strip()

    # 1. 检查是否为纯噪声短语
    if _NOISE_PHRASE_RE.match(cleaned):
        return None

    # 2. 清理英文噪声前缀（如 "the 对他" -> "对他"）
    cleaned = _EN_NOISE_PREFIX_RE.sub("", cleaned).strip()

    # 3. 清理重复词
    for pattern, replacement in _REPEAT_PATTERNS:
        cleaned = pattern.sub(replacement, cleaned)

    # 4. 数字规范化：中文数字年份 -> 阿拉伯数字
    cleaned = _YEAR_RE.sub(_cn_digits_to_arabic, cleaned)
    cleaned = _FOUR_DIGIT_CN_RE.sub(_cn_digits_to_arabic, cleaned)

    # 5. 检查清理后是否为空或纯标点
    stripped = cleaned
    for punc in "，。、！？；：,.!?;: ":
        stripped = stripped.replace(punc, "")
    if not stripped:
        return None

    # 6. 检查是否为纯语气词
    if stripped in _NOISE_WORDS_CN or len(stripped) <= 2 and all(c in _NOISE_WORDS_CN for c in stripped):
        return None

    return cleaned

SYSTEM_PROMPT = """\
你是一个专业的文本校对工具。
任务：接收ASR语音转写文本，输出修正后的文本。
要求：
1. 仅输出修正后的正文，严禁输出任何开场白、解释、修正列表或Markdown标记。
2. 修正同音字错误（如"受权"->"授权"）。
3. 修正错误标点符号，使其符合阅读习惯。
4. 保持原句意，不要重写或删减内容。
5. 如果文本包含无法确定的口语，保留原样。"""

TRANSCRIPT_SYSTEM_PROMPT = """\
你是一个字幕校对专家。
输入是一个JSON对象，entries字段包含句子ID和原始内容。
任务：对每个 text 字段做轻度润色，使其更适合阅读。

规则：
1. 绝对严禁修改 id 字段。
2. 绝对严禁合并或拆分句子。
3. 去除无意义的口语填充词（如"那个""就是说""嗯"等），但保持句意完整。
4. 修正口语倒装（如"我走了先"->"我先走了"）。
5. 保留原有标点符号，仅在明显断句错误时微调。
6. 严禁臆造原文中没有的事实，严禁大幅改写。
7. 输出必须是包含 entries 字段的JSON对象。

【输入示例】
{"entries": [{"id": 1, "text": "嗯那个今天的会议呢主要是关于明年的计划。"}, {"id": 2, "text": "我觉得这个方案还是可以的就是说需要再优化一下。"}]}

【输出示例】
{"entries": [{"id": 1, "text": "今天的会议主要是关于明年的计划。"}, {"id": 2, "text": "我觉得这个方案还是可以的，需要再优化一下。"}]}"""


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
        filtered_ids: set[int] = set()  # 被过滤的纯噪声条目

        for entry in entries:
            entry_id = entry["id"]
            original_text = entry.get("text", "")
            cleaned = preprocess_text(original_text)

            if cleaned is None:
                # 纯噪声，标记为过滤
                filtered_ids.add(entry_id)
            elif cleaned != original_text.strip():
                # 有变化，使用清理后的文本
                preprocessed_entries.append({"id": entry_id, "text": cleaned})
            else:
                # 无变化，保持原样
                preprocessed_entries.append(entry)

        logger.info(
            "Phase 1 (rule-based): %d entries -> %d valid, %d filtered as noise",
            len(entries),
            len(preprocessed_entries),
            len(filtered_ids),
        )

        # 如果所有条目都被过滤，直接返回空结果
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

        # 为被过滤的噪声条目设置空字符串
        for entry_id in filtered_ids:
            merged[entry_id] = ""

        return merged

    @staticmethod
    def _create_transcript_batches(
        entries: list[dict],
        max_entries: int = 15,
        max_chars: int = 800,
    ) -> list[list[dict]]:
        """创建同时满足条目数和字符数限制的批次

        Args:
            entries: 待处理的条目列表
            max_entries: 每批最大条目数
            max_chars: 每批最大字符数

        Returns:
            分批后的条目列表
        """
        batches: list[list[dict]] = []
        current_batch: list[dict] = []
        current_chars = 0

        for entry in entries:
            entry_chars = len(entry.get("text", ""))

            # 单条条目超过字符限制：作为独立批次
            if entry_chars > max_chars:
                # 先提交当前批次
                if current_batch:
                    batches.append(current_batch)
                    current_batch = []
                    current_chars = 0
                # 将超大条目作为独立批次
                batches.append([entry])
                continue

            # 添加后会超过限制：提交当前批次
            would_exceed_entries = len(current_batch) >= max_entries
            would_exceed_chars = current_chars + entry_chars > max_chars

            if current_batch and (would_exceed_entries or would_exceed_chars):
                batches.append(current_batch)
                current_batch = []
                current_chars = 0

            current_batch.append(entry)
            current_chars += entry_chars

        # 提交最后一个批次
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
            # 使用 num_predict 限制输出长度，并显式禁用 thinking
            # 公式：输入字符 * 2（中文token转换）+ 1024（JSON 格式开销）
            # 禁用 thinking 后输出更简洁，不需要大缓冲区
            max_output_tokens = min(4096, batch_chars * 2 + 1024)

            response = await self._client.chat(
                messages=[
                    {"role": "system", "content": TRANSCRIPT_SYSTEM_PROMPT},
                    {"role": "user", "content": input_json},
                ],
                num_ctx=self._num_ctx,
                json_format=True,
                think=False,  # 禁用 thinking 确保输出完整
                num_predict=max_output_tokens,  # 限制输出长度
            )
            raw = response.content
            raw = _THINK_RE.sub("", raw).strip()

            if not raw:
                logger.warning("LLM returned empty response for transcript batch, using fallback")
                return fallback

            parsed = json.loads(raw)

            # Extract entries array from wrapper object or handle bare array
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
            return _THINK_RE.sub("", content).strip() or text
        except Exception as e:
            logger.warning(
                "LLM correction failed for chunk, using raw text: [%s] %s",
                type(e).__name__,
                e or "(no message)",
            )
            return text
