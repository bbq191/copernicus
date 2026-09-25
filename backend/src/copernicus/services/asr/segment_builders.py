"""把 FunASR 的原始输出整理成 Segment 列表，并记录置信度统计（纯函数）。"""

import logging

from copernicus.services.asr.types import Segment

logger = logging.getLogger(__name__)

_PUNCTUATION = frozenset("。！？；，、：\u201c\u201d\u2018\u2019（）《》【】…—·\n.!?;,:\"'()[]")


def build_segments_from_sentences(sentences: list[str], token_conf: list[float]) -> list[Segment]:
    """从纯句子列表构建 Segment 对象（降级路径）：按字对齐逐字置信度，标点不占位。"""
    if not token_conf:
        return [Segment(text=s) for s in sentences]

    segments: list[Segment] = []
    conf_idx = 0

    for sent in sentences:
        scores: list[float] = []
        for ch in sent:
            if ch in _PUNCTUATION:
                continue
            if conf_idx < len(token_conf):
                scores.append(token_conf[conf_idx])
                conf_idx += 1
        avg_conf = sum(scores) / len(scores) if scores else 0.0
        segments.append(Segment(text=sent, confidence=avg_conf))

    return segments


def build_segments_from_sentence_info(
    sentence_info: list[dict],
    token_conf: list[float],
) -> list[Segment]:
    """从带时间戳和说话人信息的 FunASR sentence_info 构建 Segment 对象。"""
    segments: list[Segment] = []
    conf_offset = 0

    for item in sentence_info:
        n_tokens = len(item.get("timestamp", []))

        if token_conf and n_tokens > 0 and conf_offset < len(token_conf):
            chunk = token_conf[conf_offset : conf_offset + n_tokens]
            avg_conf = sum(chunk) / len(chunk) if chunk else 0.0
            conf_offset += n_tokens
        else:
            avg_conf = 0.0

        segments.append(
            Segment(
                text=item.get("text", ""),
                start_ms=item.get("start", 0),
                end_ms=item.get("end", 0),
                confidence=avg_conf,
                speaker=item.get("spk", -1),
            )
        )
    return segments


def log_confidence_stats(segments: list[Segment]) -> None:
    """记录分段的置信度统计信息。"""
    if not segments or segments[0].confidence == 0.0:
        return

    confs = [s.confidence for s in segments]
    logger.info(
        "Confidence stats: min=%.4f, max=%.4f, avg=%.4f, >=0.95: %d/%d",
        min(confs),
        max(confs),
        sum(confs) / len(confs),
        sum(1 for c in confs if c >= 0.95),
        len(confs),
    )
