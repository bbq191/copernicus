"""LLM 输出解析工具函数。

用于剥离 think 标签和从 LLM 响应中提取 JSON 的公共函数。
"""

import re

_THINK_PAIR_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_THINK_OPEN_RE = re.compile(r"<think>.*", re.DOTALL)
_THINK_CLOSE_RE = re.compile(r"^.*?</think>", re.DOTALL)


def strip_think_tags(text: str) -> str:
    """移除 LLM 输出中的 <think>...</think> 标签。"""
    text = _THINK_PAIR_RE.sub("", text)
    text = _THINK_OPEN_RE.sub("", text)
    text = _THINK_CLOSE_RE.sub("", text)
    return text


def _preprocess_llm_output(text: str) -> str:
    text = strip_think_tags(text)
    return text.replace("```json", "").replace("```", "").strip()


def extract_json_object(text: str) -> str:
    """从 LLM 输出中提取 JSON 对象，自动剥离 think 标签和 Markdown 代码块。"""
    text = _preprocess_llm_output(text)
    idx = text.find("{")
    if idx > 0:
        text = text[idx:]
    last = text.rfind("}")
    if last >= 0:
        text = text[: last + 1]
    return text.strip()


def extract_json_array(text: str) -> str:
    """从 LLM 输出中提取 JSON 数组，自动剥离 think 标签和 Markdown 代码块。"""
    text = _preprocess_llm_output(text)
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
