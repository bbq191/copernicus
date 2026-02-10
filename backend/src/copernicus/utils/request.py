"""请求参数解析工具函数

Author: afu
"""

import json


def parse_hotwords(hotwords: str | None) -> list[str] | None:
    """解析请求中的 hotwords JSON 字符串

    Args:
        hotwords: JSON 格式的热词字符串，如 '["词1", "词2"]'

    Returns:
        热词列表，或 None（无热词时）

    Raises:
        ValueError: hotwords 不是合法的 JSON 字符串数组
    """
    if not hotwords:
        return None
    try:
        parsed = json.loads(hotwords)
    except json.JSONDecodeError as e:
        raise ValueError(f"hotwords 不是合法 JSON: {e}") from e
    if not isinstance(parsed, list) or not all(isinstance(w, str) for w in parsed):
        raise ValueError("hotwords 必须是字符串数组，如 [\"词1\", \"词2\"]")
    return parsed if parsed else None
