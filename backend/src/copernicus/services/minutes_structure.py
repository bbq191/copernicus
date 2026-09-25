"""会议纪要的结构化提取：行动项与决议，并回溯到转写中的时间点。

与"排版纪要"是两次独立的 LLM 调用：排版由模板决定格式，这里固定输出结构，便于界面列表化与跳转。
LLM 只需给出一句从原文摘抄的"引文"，时间点由服务端在转写里匹配得到——模型不擅长报时间，
而匹配不到就留空，不会给出错误的时间。

作者：afu
"""

import asyncio
import difflib
import json
import logging
import re
from dataclasses import dataclass, field

from copernicus.config import Settings
from copernicus.schemas.evaluation import ActionItem, Decision, StructureStatus
from copernicus.schemas.transcription import TranscriptEntrySchema
from copernicus.services.llm import LLMClient
from copernicus.utils.llm_parse import extract_json_object

logger = logging.getLogger(__name__)

_IGNORED_CHARS = re.compile(r"[\s，。、！？；：,.!?;:\"'“”‘’（）()《》【】\-—…]+")
_MIN_QUOTE_CHARS = 4       # 更短的引文没有区分度，不做匹配
_MIN_FUZZY_COVERAGE = 0.6  # 模糊匹配：按序匹配上的字数至少占引文的这一比例
_MIN_FUZZY_BLOCK = 2       # 模糊匹配只统计连续 2 字以上的匹配片段

SYSTEM_PROMPT = """你是会议纪要助手。请只从给定的会议转写片段中提取两类内容：
1. 行动项：会上明确提出、需要有人去做的事。
2. 决议：会上明确达成的结论或做出的决定。

规则：
- 只提取转写里明确说出的内容，不得推断或补充；没有就返回空数组。
- owner（负责人）、due（时间要求）只有在转写里明确说了才填，否则留空字符串。
- 每一项都必须带 quote：从转写中原样摘抄的一句话（不超过 40 字，不要改写），用于在录音里定位。
- 只输出一个合法 JSON 对象，不要输出解释。

输出格式：
{"action_items": [{"task": "", "owner": "", "due": "", "quote": ""}], "decisions": [{"content": "", "quote": ""}]}"""


@dataclass
class StructuredMinutes:
    action_items: list[ActionItem] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)
    status: StructureStatus = "ok"


def _normalize(text: str) -> str:
    return _IGNORED_CHARS.sub("", text).lower()


def locate_quote(quote: str, entries: list[TranscriptEntrySchema]) -> int | None:
    """在转写中找到引文所在句段，返回其起始毫秒；找不到返回 None。

    依次尝试：单句包含 → 相邻两句拼接包含（引文跨句）→ 按序匹配字数占比达标的模糊匹配。
    """
    q = _normalize(quote)
    if len(q) < _MIN_QUOTE_CHARS:
        return None
    texts = [_normalize(e.text_corrected or e.text) for e in entries]

    for entry, text in zip(entries, texts, strict=True):
        if q in text:
            return entry.timestamp_ms
    for i in range(len(entries) - 1):
        if q in texts[i] + texts[i + 1]:
            return entries[i].timestamp_ms

    best_ms, best_matched = None, 0
    for entry, text in zip(entries, texts, strict=True):
        blocks = difflib.SequenceMatcher(None, q, text, autojunk=False).get_matching_blocks()
        matched = sum(b.size for b in blocks if b.size >= _MIN_FUZZY_BLOCK)  # 单字巧合不计
        if matched > best_matched:
            best_ms, best_matched = entry.timestamp_ms, matched
    return best_ms if best_matched / len(q) >= _MIN_FUZZY_COVERAGE else None


def _chunk_entries(entries: list[TranscriptEntrySchema], chunk_chars: int, max_chars: int) -> list[list[TranscriptEntrySchema]]:
    """按字符预算把句段分组；累计超过 max_chars 的部分不处理（与纪要生成的截断上限一致）。"""
    chunks: list[list[TranscriptEntrySchema]] = []
    current: list[TranscriptEntrySchema] = []
    size = total = 0
    for entry in entries:
        n = len(entry.text_corrected or entry.text) + 8
        if total + n > max_chars:
            break
        if current and size + n > chunk_chars:
            chunks.append(current)
            current, size = [], 0
        current.append(entry)
        size += n
        total += n
    if current:
        chunks.append(current)
    return chunks


class MinutesStructurer:
    def __init__(self, client: LLMClient, settings: Settings) -> None:
        self._client = client
        self._enabled = settings.minutes_structure_enabled
        self._chunk_chars = settings.evaluation_chunk_size
        self._max_chars = settings.evaluation_max_text_chars
        self._num_ctx = settings.evaluation_num_ctx

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def extract(self, entries: list[TranscriptEntrySchema]) -> StructuredMinutes:
        """提取行动项与决议。全部分块都失败时抛出异常，由调用方降级。"""
        chunks = _chunk_entries(entries, self._chunk_chars, self._max_chars)
        if not chunks:
            return StructuredMinutes(status="ok")

        results = await asyncio.gather(*(self._extract_chunk(c) for c in chunks), return_exceptions=True)
        failures = [r for r in results if isinstance(r, BaseException)]
        if len(failures) == len(results):
            raise failures[0]

        minutes = StructuredMinutes(status="partial" if failures else "ok")
        seen: set[str] = set()
        for chunk_minutes in (r for r in results if not isinstance(r, BaseException)):
            for item in chunk_minutes.action_items:
                if _remember(seen, "a", item.task):
                    minutes.action_items.append(item)
            for decision in chunk_minutes.decisions:
                if _remember(seen, "d", decision.content):
                    minutes.decisions.append(decision)
        logger.info(
            "Structured minutes: %d action items, %d decisions (%d/%d chunks failed)",
            len(minutes.action_items), len(minutes.decisions), len(failures), len(results),
        )
        return minutes

    async def _extract_chunk(self, chunk: list[TranscriptEntrySchema]) -> StructuredMinutes:
        transcript = "\n".join(f"{e.speaker}：{e.text_corrected or e.text}" for e in chunk)
        response = await self._client.chat(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"【转写片段开始】\n{transcript}\n【转写片段结束】"},
            ],
            json_format=True,
            num_ctx=self._num_ctx,
            think=False,
            num_predict=2048,
        )
        data = json.loads(extract_json_object(response.content))
        return _parse_chunk(data, chunk)


def _remember(seen: set[str], kind: str, text: str) -> bool:
    key = f"{kind}:{_normalize(text)}"
    if key in seen:
        return False
    seen.add(key)
    return True


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _parse_chunk(data: object, chunk: list[TranscriptEntrySchema]) -> StructuredMinutes:
    """容错解析 LLM 输出：字段缺失或类型不对的条目直接丢弃，不让一个坏条目毁掉整块。"""
    if not isinstance(data, dict):
        raise ValueError("结构化提取的输出不是 JSON 对象")
    minutes = StructuredMinutes()
    for raw in data.get("action_items") or []:
        if isinstance(raw, dict) and _text(raw.get("task")):
            minutes.action_items.append(ActionItem(
                task=_text(raw["task"]),
                owner=_text(raw.get("owner")),
                due=_text(raw.get("due")),
                timestamp_ms=locate_quote(_text(raw.get("quote")), chunk),
            ))
    for raw in data.get("decisions") or []:
        if isinstance(raw, dict) and _text(raw.get("content")):
            minutes.decisions.append(Decision(
                content=_text(raw["content"]),
                timestamp_ms=locate_quote(_text(raw.get("quote")), chunk),
            ))
    return minutes
