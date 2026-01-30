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
