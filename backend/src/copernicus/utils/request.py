import json

_HOTWORDS_MAX_COUNT = 200
_HOTWORDS_MAX_WORD_LEN = 100


def parse_hotwords(hotwords: str | None) -> list[str] | None:
    """解析请求中的 hotwords JSON 字符串。

    Raises:
        ValueError: 格式非法、数量超限或单词过长
    """
    if not hotwords:
        return None
    try:
        parsed = json.loads(hotwords)
    except json.JSONDecodeError as e:
        raise ValueError(f"hotwords 不是合法 JSON: {e}") from e
    if not isinstance(parsed, list) or not all(isinstance(w, str) for w in parsed):
        raise ValueError("hotwords 必须是字符串数组，如 [\"词1\", \"词2\"]")
    return validate_hotwords(parsed)


def validate_hotwords(words: list[str]) -> list[str] | None:
    """校验热词数量与长度（表单与分片上传两条路径共用）；空列表返回 None。

    Raises:
        ValueError: 数量超限或单词过长
    """
    if len(words) > _HOTWORDS_MAX_COUNT:
        raise ValueError(f"hotwords 数量超限（最多 {_HOTWORDS_MAX_COUNT} 条，实际 {len(words)} 条）")
    for w in words:
        if len(w) > _HOTWORDS_MAX_WORD_LEN:
            raise ValueError(f"热词长度超限（最多 {_HOTWORDS_MAX_WORD_LEN} 字符）：{w[:20]!r}…")
    return words or None
