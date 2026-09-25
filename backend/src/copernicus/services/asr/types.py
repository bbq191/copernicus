"""ASR 输出的数据结构。"""

from dataclasses import dataclass, field


@dataclass
class SubSentence:
    """预合并时保留的原始 ASR 句子边界。"""

    text: str
    start_ms: int = 0
    end_ms: int = 0


@dataclass
class Segment:
    text: str
    start_ms: int = 0
    end_ms: int = 0
    confidence: float = 0.0
    speaker: int = -1
    sub_sentences: list[SubSentence] = field(default_factory=list)


@dataclass
class ASRResult:
    text: str
    segments: list[Segment] = field(default_factory=list)
