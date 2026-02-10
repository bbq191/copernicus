"""LLM output parsing utilities.

Shared helpers for stripping think tags and extracting JSON from LLM responses.
"""

import re

_THINK_PAIR_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_THINK_OPEN_RE = re.compile(r"<think>.*", re.DOTALL)
_THINK_CLOSE_RE = re.compile(r"^.*?</think>", re.DOTALL)


def strip_think_tags(text: str) -> str:
    """Remove <think>...</think> tags from LLM output."""
    text = _THINK_PAIR_RE.sub("", text)
    text = _THINK_OPEN_RE.sub("", text)
    text = _THINK_CLOSE_RE.sub("", text)
    return text


def extract_json_object(text: str) -> str:
    """Extract a JSON object from LLM output, stripping think tags and markdown fences."""
    text = strip_think_tags(text)
    text = text.replace("```json", "").replace("```", "").strip()
    idx = text.find("{")
    if idx > 0:
        text = text[idx:]
    last = text.rfind("}")
    if last >= 0:
        text = text[: last + 1]
    return text.strip()


def extract_json_array(text: str) -> str:
    """Extract a JSON array from LLM output, stripping think tags and markdown fences."""
    text = strip_think_tags(text)
    text = text.replace("```json", "").replace("```", "").strip()
    start = text.find("[")
    if start >= 0:
        end = text.rfind("]")
        if end > start:
            return text[start : end + 1]
    # Fallback: LLM may have wrapped array in an object like {"violations": [...]}
    start = text.find("{")
    if start >= 0:
        end = text.rfind("}")
        if end > start:
            return text[start : end + 1]
    return text.strip()
