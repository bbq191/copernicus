def chunk_text(text: str, chunk_size: int = 800, overlap: int = 100) -> list[str]:
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


def merge_chunks(chunks: list[str], overlap: int = 100) -> str:
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
