from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from copernicus.services.asr import Segment


def chunk_text(text: str, chunk_size: int = 800, overlap: int = 50) -> list[str]:
    """Split text into overlapping chunks for LLM context windowing.

    Tries to split at sentence boundaries (punctuation) to avoid cutting
    mid-sentence. Falls back to hard split if no boundary is found.
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
    """Reassemble corrected chunks, deduplicating overlap regions.

    Since LLM correction may alter the overlap content, we use a simple
    strategy: keep the first chunk fully, then for subsequent chunks
    skip the first `overlap` characters (which were also present at the
    end of the previous chunk).
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
    """Split text into sentences using punctuation boundaries."""
    if not text:
        return []
    parts = re.split(r"(?<=[。！？；\n])", text)
    sentences = [p for p in parts if p.strip()]
    return sentences if sentences else [text]


def format_timestamp(ms: int) -> str:
    """Convert milliseconds to MM:SS display format."""
    total_seconds = ms // 1000
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes:02d}:{seconds:02d}"


def pre_merge_segments(
    segments: list[Segment],
    gap_ms: int = 500,
) -> list[Segment]:
    """Pre-merge fine-grained ASR segments before LLM correction.

    Combines consecutive segments from the same speaker when the time gap
    between them is small. This reduces the total segment count (e.g. from
    1400 to ~300), which cuts the number of LLM batches and gives the model
    better context per request.

    Merged segment confidence is the weighted average by text length.
    """
    from copernicus.services.asr import Segment as _Seg

    if not segments:
        return []

    merged: list[Segment] = []
    cur = _Seg(
        text=segments[0].text,
        start_ms=segments[0].start_ms,
        end_ms=segments[0].end_ms,
        confidence=segments[0].confidence,
        speaker=segments[0].speaker,
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
        else:
            merged.append(cur)
            cur = _Seg(
                text=seg.text,
                start_ms=seg.start_ms,
                end_ms=seg.end_ms,
                confidence=seg.confidence,
                speaker=seg.speaker,
            )

    merged.append(cur)
    return merged


def smooth_speakers(
    segments: list[Segment],
    max_duration_ms: int = 1500,
) -> list[Segment]:
    """Smooth speaker diarization flicker.

    If a segment's speaker differs from both its predecessor and successor,
    and the segment duration is short (below max_duration_ms), force its
    speaker to match the surrounding context.
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
    """Merge consecutive transcript entries from the same speaker.

    Each entry is {"timestamp": str, "timestamp_ms": int, "speaker": str,
    "text": str, "text_corrected": str}.

    Entries are merged when the speaker is the same and the time gap between
    the current entry's start and the previous entry's start is within the
    threshold.
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


def group_segments(segments: list[Segment], chunk_size: int = 800) -> list[list[Segment]]:
    """Group ASR segments into chunks that fit within chunk_size characters.

    Segments are grouped greedily: each group accumulates segments until
    adding the next one would exceed chunk_size, then a new group starts.
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
