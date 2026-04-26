from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from copernicus.services.asr import Segment, SubSentence


def chunk_text(text: str, chunk_size: int = 800, overlap: int = 50) -> list[str]:
    """将文本切分为带重叠的分块，供 LLM 上下文窗口使用。

    优先在句子边界（标点符号）处切分，避免句子中断。
    若未找到边界则回退为硬切分。
    """
    if len(text) <= chunk_size:
        return [text]

    sentence_endings = {"。", "！", "？", ".", "!", "?", "；", ";", "\n"}
    chunks: list[str] = []
    start = 0

    while start < len(text):
        end = start + chunk_size

        if end >= len(text):
            chunks.append(text[start:])
            break

        # Look backwards from `end` for a sentence boundary
        split_pos = end
        for i in range(end, max(start + chunk_size // 2, start), -1):
            if text[i] in sentence_endings:
                split_pos = i + 1
                break

        chunks.append(text[start:split_pos])
        start = split_pos - overlap

    return chunks


def merge_chunks(chunks: list[str], overlap: int = 50) -> str:
    """重新拼接纠正后的分块，去重重叠区域。

    由于 LLM 纠正可能改变重叠内容，采用简单策略：
    第一个分块完整保留，后续分块跳过开头 overlap 个字符
    （这些字符已出现在上一分块末尾）。
    """
    if not chunks:
        return ""
    if len(chunks) == 1:
        return chunks[0]

    parts = [chunks[0]]
    for chunk in chunks[1:]:
        # Skip the overlap portion from the beginning of each subsequent chunk
        skip = min(overlap, len(chunk))
        parts.append(chunk[skip:])

    return "".join(parts)


def split_sentences(text: str) -> list[str]:
    """按标点边界将文本切分为句子列表。"""
    if not text:
        return []
    parts = re.split(r"(?<=[。！？；\n])", text)
    sentences = [p for p in parts if p.strip()]
    return sentences if sentences else [text]


def format_timestamp(ms: int) -> str:
    """将毫秒转换为 MM:SS 显示格式。"""
    total_seconds = ms // 1000
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes:02d}:{seconds:02d}"


def pre_merge_segments(
    segments: list[Segment],
    gap_ms: int = 500,
) -> list[Segment]:
    """在 LLM 纠正前预合并细粒度 ASR 分段。

    将同一说话人的相邻分段在时间间隔较小时合并，
    从而减少总分段数（如从 1400 条降至约 300 条），
    减少 LLM 批次数并为每次请求提供更好的上下文。

    合并后的分段置信度为按文本长度加权平均值。
    每个合并分段在 sub_sentences 中保留原始句子边界，
    供后续细粒度拆分使用。
    """
    from copernicus.services.asr import Segment as _Seg, SubSentence

    if not segments:
        return []

    def _to_sub(seg: Segment) -> SubSentence:
        return SubSentence(text=seg.text, start_ms=seg.start_ms, end_ms=seg.end_ms)

    merged: list[Segment] = []
    cur = _Seg(
        text=segments[0].text,
        start_ms=segments[0].start_ms,
        end_ms=segments[0].end_ms,
        confidence=segments[0].confidence,
        speaker=segments[0].speaker,
        sub_sentences=[_to_sub(segments[0])],
    )

    for seg in segments[1:]:
        same_speaker = seg.speaker == cur.speaker
        within_gap = (seg.start_ms - cur.end_ms) < gap_ms

        if same_speaker and within_gap:
            # Weighted average confidence
            len_cur = len(cur.text)
            len_seg = len(seg.text)
            total_len = len_cur + len_seg
            if total_len > 0:
                cur.confidence = (
                    cur.confidence * len_cur + seg.confidence * len_seg
                ) / total_len
            cur.text += seg.text
            cur.end_ms = seg.end_ms
            cur.sub_sentences.append(_to_sub(seg))
        else:
            merged.append(cur)
            cur = _Seg(
                text=seg.text,
                start_ms=seg.start_ms,
                end_ms=seg.end_ms,
                confidence=seg.confidence,
                speaker=seg.speaker,
                sub_sentences=[_to_sub(seg)],
            )

    merged.append(cur)
    return merged


def smooth_speakers(
    segments: list[Segment],
    max_duration_ms: int = 1500,
) -> list[Segment]:
    """平滑说话人分离的抖动噪声。

    若某分段的说话人与前后分段均不同，
    且该分段时长较短（低于 max_duration_ms），
    则强制将其说话人修正为周围分段的说话人。
    """
    if len(segments) < 3:
        return segments

    for i in range(1, len(segments) - 1):
        prev_spk = segments[i - 1].speaker
        curr_spk = segments[i].speaker
        next_spk = segments[i + 1].speaker
        duration = segments[i].end_ms - segments[i].start_ms

        if curr_spk != prev_spk and prev_spk == next_spk and duration < max_duration_ms:
            segments[i].speaker = prev_spk

    return segments


def merge_transcript_entries(
    entries: list[dict],
    gap_threshold_ms: int = 2000,
) -> list[dict]:
    """合并同一说话人的相邻转写条目。

    每条条目格式为 {"timestamp": str, "timestamp_ms": int, "speaker": str,
    "text": str, "text_corrected": str}。

    当说话人相同且当前条目与前一条目的起始时间差在阈值内时合并。
    """
    if not entries:
        return []

    merged: list[dict] = []
    current = dict(entries[0])

    for entry in entries[1:]:
        same_speaker = entry["speaker"] == current["speaker"]
        within_gap = (entry["timestamp_ms"] - current["timestamp_ms"]) < gap_threshold_ms

        if same_speaker and within_gap:
            current["text"] += entry["text"]
            current["text_corrected"] += entry["text_corrected"]
        else:
            merged.append(current)
            current = dict(entry)

    merged.append(current)
    return merged


def split_corrected_by_sub_sentences(
    corrected_text: str,
    sub_sentences: list[SubSentence],
) -> list[SubSentence]:
    """将 LLM 纠正后的文本拆分回子句粒度。

    基于标点切分，按比例将每个片段映射到原始子句的时间区间。

    返回带有纠正文本和估算 start_ms / end_ms 的 SubSentence 列表。
    """
    from copernicus.services.asr import SubSentence as _Sub

    if not sub_sentences or not corrected_text.strip():
        return [_Sub(text=corrected_text, start_ms=0, end_ms=0)]

    if len(sub_sentences) == 1:
        return [
            _Sub(
                text=corrected_text,
                start_ms=sub_sentences[0].start_ms,
                end_ms=sub_sentences[0].end_ms,
            )
        ]

    # Split corrected text by sentence-ending punctuation
    fragments = split_sentences(corrected_text)
    if not fragments:
        fragments = [corrected_text]

    # Compute total time span from original sub-sentences
    total_start = sub_sentences[0].start_ms
    total_end = sub_sentences[-1].end_ms
    total_duration = max(total_end - total_start, 1)

    # Proportionally allocate time by character length
    total_chars = sum(len(f) for f in fragments)
    if total_chars == 0:
        total_chars = 1

    result: list[SubSentence] = []
    cursor_ms = total_start

    for i, frag in enumerate(fragments):
        ratio = len(frag) / total_chars
        duration = round(total_duration * ratio)
        frag_start = cursor_ms
        frag_end = cursor_ms + duration if i < len(fragments) - 1 else total_end
        result.append(_Sub(text=frag, start_ms=frag_start, end_ms=frag_end))
        cursor_ms = frag_end

    return result


def split_original_by_sub_sentences(
    original_text: str,
    sub_sentences: list[SubSentence],
) -> list[str]:
    """使用子句边界切分纠正前的原始文本。

    原始文本由各子句文本拼接而成，因此可通过前缀匹配切分。
    匹配失败时回退为标点切分。
    """
    if len(sub_sentences) <= 1:
        return [original_text]

    result: list[str] = []
    remaining = original_text

    for i, sub in enumerate(sub_sentences):
        if i == len(sub_sentences) - 1:
            # Last sub-sentence gets everything remaining
            result.append(remaining)
        elif remaining.startswith(sub.text):
            result.append(sub.text)
            remaining = remaining[len(sub.text) :]
        else:
            # Mismatch — fallback: return remaining as a single entry
            result.append(remaining)
            remaining = ""

    # If mismatch caused early exit, pad with empty strings
    while len(result) < len(sub_sentences):
        result.append("")

    return result


def group_segments(segments: list[Segment], chunk_size: int = 800) -> list[list[Segment]]:
    """将 ASR 分段贪心地分组为不超过 chunk_size 字符的批次。

    每组持续累积分段，直到加入下一个分段会超过 chunk_size 时开启新组。
    """
    if not segments:
        return []

    groups: list[list[Segment]] = []
    current_group: list[Segment] = []
    current_length = 0

    for seg in segments:
        seg_len = len(seg.text)
        if current_group and current_length + seg_len > chunk_size:
            groups.append(current_group)
            current_group = []
            current_length = 0
        current_group.append(seg)
        current_length += seg_len

    if current_group:
        groups.append(current_group)

    return groups
