import re

_NOISE_PHRASE_RE = re.compile(
    r"^\s*(?:the\s+)*(?:the|a|an|yeah|yes|no|ok|okay|um|uh|oh|ah|er|hmm|hm|mm)\s*[，。,.]?\s*$",
    re.IGNORECASE,
)

_NOISE_WORDS_CN = {"嗯", "啊", "哦", "呃", "唔", "嘿", "哈", "呵", "噢", "喔", "诶", "哎", "唉", "呀"}

_REPEAT_PATTERNS = [
    (re.compile(r"(那个){2,}"), "那个"),
    (re.compile(r"(这个){2,}"), "这个"),
    (re.compile(r"(就是){2,}"), "就是"),
    (re.compile(r"(然后){2,}"), "然后"),
    (re.compile(r"(所以){2,}"), "所以"),
    (re.compile(r"(但是){2,}"), "但是"),
    (re.compile(r"(因为){2,}"), "因为"),
    (re.compile(r"(可能){2,}"), "可能"),
    (re.compile(r"(应该){2,}"), "应该"),
    (re.compile(r"(终于){2,}"), "终于"),
    (re.compile(r"(了解){2,}"), "了解"),
    (re.compile(r"(不好意思){2,}"), "不好意思"),
    (re.compile(r"(嗯){2,}"), "嗯"),
    (re.compile(r"(啊){2,}"), "啊"),
    (re.compile(r"(哦){2,}"), "哦"),
    (re.compile(r"(呃){2,}"), "呃"),
]

_EN_NOISE_PREFIX_RE = re.compile(r"^\s*(?:the\s+)+", re.IGNORECASE)

_CN_DIGIT_MAP = {
    "零": "0", "〇": "0", "一": "1", "二": "2", "三": "3",
    "四": "4", "五": "5", "六": "6", "七": "7", "八": "8", "九": "9",
}

_YEAR_RE = re.compile(
    r"([一二三四五六七八九])"
    r"([零〇])"
    r"([一二三四五六七八九零〇])"
    r"([一二三四五六七八九零〇])"
    r"(?=年)"
)

_FOUR_DIGIT_CN_RE = re.compile(
    r"([一二三四五六七八九])"
    r"([零〇])"
    r"([一二三四五六七八九零〇])"
    r"([一二三四五六七八九零〇])"
)


def _cn_digits_to_arabic(match: re.Match) -> str:
    return "".join(_CN_DIGIT_MAP.get(c, c) for c in match.group())


def preprocess_text(text: str) -> str | None:
    """阶段 1：规则预处理，快速清理噪声和明显错误

    Returns:
        清理后的文本，如果是纯噪声则返回 None
    """
    if not text or not text.strip():
        return None

    cleaned = text.strip()

    if _NOISE_PHRASE_RE.match(cleaned):
        return None

    cleaned = _EN_NOISE_PREFIX_RE.sub("", cleaned).strip()

    for pattern, replacement in _REPEAT_PATTERNS:
        cleaned = pattern.sub(replacement, cleaned)

    cleaned = _YEAR_RE.sub(_cn_digits_to_arabic, cleaned)
    cleaned = _FOUR_DIGIT_CN_RE.sub(_cn_digits_to_arabic, cleaned)

    stripped = cleaned
    for punc in "，。、！？；：,.!?;: ":
        stripped = stripped.replace(punc, "")
    if not stripped:
        return None

    if stripped in _NOISE_WORDS_CN or len(stripped) <= 2 and all(c in _NOISE_WORDS_CN for c in stripped):
        return None

    return cleaned
