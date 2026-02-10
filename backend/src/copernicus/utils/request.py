"""请求参数解析工具函数

Author: afu
"""

import json
import logging

logger = logging.getLogger(__name__)


def parse_hotwords(hotwords: str | None) -> list[str] | None:
    """解析请求中的 hotwords JSON 字符串

    Args:
        hotwords: JSON 格式的热词字符串，如 '["词1", "词2"]'

    Returns:
        热词列表，或 None（无热词时）
    """
    if not hotwords:
        return None
    try:
        parsed = json.loads(hotwords)
        if isinstance(parsed, list) and all(isinstance(w, str) for w in parsed):
            return parsed
    except json.JSONDecodeError:
        logger.warning("Invalid hotwords JSON: %s", hotwords[:100])
    return None
