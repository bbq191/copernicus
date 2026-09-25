"""SenseVoice 输出的文本清洗、噪声判定与超长段切分（纯函数）。"""

import re

# SenseVoice 文本清洗预编译正则（避免热路径重复编译）
_SENSEVOICE_TAG_RE = re.compile(r"<\|[^|]+\|>")
_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001F9FF"
    "\U00002600-\U000027BF"
    "\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F6FF"
    "]+",
    flags=re.UNICODE,
)
_REPEATED_PUNC_RE = re.compile(r"[。，、！？；：]{2,}")
_ISOLATED_PUNC_RE = re.compile(r"^\s*[。，、！？；：]+\s*$")

# 中文语气词和常见噪声
_NOISE_WORDS_CN = frozenset({
    "嗯", "啊", "哦", "呃", "唔", "嘿", "哈", "呵",
    "噢", "喔", "诶", "哎", "唉", "呀", "吧", "呢",
    "嘛", "咯", "喽", "哇", "嗯嗯", "啊啊", "哦哦",
})

# 英文噪声词（ASR 幻觉常见）
_NOISE_WORDS_EN = frozenset({
    "the", "a", "an", "um", "uh", "yeah", "yes", "no",
    "oh", "ah", "er", "hmm", "hm", "mm", "mhm", "ok", "okay",
    "the the", "the yeah", "a a", "um um", "uh uh",
})

# 标点符号集合（超长段的自然切分点）
_SPLIT_PUNCTUATION = frozenset("。！？；，、：.!?;,:")


def clean_sensevoice_text(text: str) -> str:
    """清洗 SenseVoice 输出的特殊标记和 emoji"""
    text = _SENSEVOICE_TAG_RE.sub("", text)
    text = _EMOJI_RE.sub("", text)
    text = _REPEATED_PUNC_RE.sub("。", text)
    text = _ISOLATED_PUNC_RE.sub("", text)
    return text.strip()


def is_noise_segment(text: str) -> bool:
    """检查是否为纯噪声段落（仅包含语气词或无意义音节），True 表示应该过滤。"""
    # 去除标点和空白后检查
    cleaned = text.strip().lower()
    for punc in "。，、！？；：.!?;,: ":
        cleaned = cleaned.replace(punc, " ")
    cleaned = " ".join(cleaned.split())  # 规范化空白

    if not cleaned:
        return True

    if cleaned in _NOISE_WORDS_CN or cleaned in _NOISE_WORDS_EN:
        return True

    # 重复语气词组合（如 "嗯嗯嗯"、"啊啊啊"）
    if len(cleaned) <= 6:
        unique_chars = set(cleaned.replace(" ", ""))
        if len(unique_chars) <= 2 and all(c in _NOISE_WORDS_CN for c in unique_chars):
            return True

    # 仅由英文噪声词组成
    words = cleaned.split()
    return bool(words) and all(w in _NOISE_WORDS_EN for w in words)


def split_long_segment(
    text: str,
    timestamps: list[list[int]],
    max_duration_ms: int = 15000,
) -> list[dict]:
    """将超长 segment 基于时间戳切分为多个短段落。

    Args:
        text: 完整文本
        timestamps: 字级时间戳列表 [[start, end], ...]
        max_duration_ms: 单段最大时长（毫秒）

    Returns:
        切分后的 segment 列表 [{"text", "start", "end"}, ...]
    """
    if not timestamps or len(timestamps) < 2:
        return [{"text": text, "start": 0, "end": 0}]

    results: list[dict] = []
    current_start_idx = 0
    current_start_ms = timestamps[0][0]

    for i, ts in enumerate(timestamps):
        if ts[1] - current_start_ms < max_duration_ms:
            continue

        # 向前搜索最近的标点符号作为切分点；找不到就在当前位置切
        split_idx = i
        for j in range(i, current_start_idx, -1):
            if j < len(text) and text[j] in _SPLIT_PUNCTUATION:
                split_idx = j + 1
                break

        sub_text = text[current_start_idx:split_idx].strip()
        if sub_text:
            sub_end_ms = timestamps[min(split_idx - 1, len(timestamps) - 1)][1]
            results.append({
                "text": sub_text,
                "start": int(current_start_ms),
                "end": int(sub_end_ms),
            })

        current_start_idx = split_idx
        if split_idx < len(timestamps):
            current_start_ms = timestamps[split_idx][0]

    # 处理剩余部分
    if current_start_idx < len(text):
        remaining_text = text[current_start_idx:].strip()
        if remaining_text:
            results.append({
                "text": remaining_text,
                "start": int(current_start_ms),
                "end": int(timestamps[-1][1]),
            })

    return results if results else [{"text": text, "start": int(timestamps[0][0]), "end": int(timestamps[-1][1])}]
