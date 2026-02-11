"""合规审核后处理过滤器

在 Map 阶段之后、生成 summary 之前执行，降低误报率并补充证据。

过滤器链：
  ConfidenceFilter -> ExactMatchValidator -> DeduplicationFilter -> EvidenceEnricher

Author: afu
"""

from __future__ import annotations

import logging
import os
import re
from typing import TYPE_CHECKING

from pypinyin import lazy_pinyin

from copernicus.schemas.compliance import Violation
from copernicus.services.rule_registry import RuleRegistry

if TYPE_CHECKING:
    from copernicus.services.rule_registry import StructuredRule

logger = logging.getLogger(__name__)


class ConfidenceFilter:
    """丢弃 confidence < threshold 的违规。"""

    def __init__(self, threshold: float = 0.7) -> None:
        self._threshold = threshold

    def apply(self, violations: list[Violation]) -> list[Violation]:
        before = len(violations)
        result = [v for v in violations if v.confidence >= self._threshold]
        dropped = before - len(result)
        if dropped:
            logger.info(
                "ConfidenceFilter: dropped %d/%d violations (threshold=%.2f)",
                dropped,
                before,
                self._threshold,
            )
        return result


class ExactMatchValidator:
    """对 exact 模式规则进行 Python 正则二次验证。

    - LLM 报告但正则未命中：标记为误报丢弃
    - 正则命中但 LLM 遗漏：补充添加（需提供全文本）
    """

    def apply(
        self,
        violations: list[Violation],
        rules: list[StructuredRule],
        full_text: str,
    ) -> list[Violation]:
        exact_rules = {r.id: r for r in rules if r.check_mode == "exact"}
        if not exact_rules:
            return violations

        validated: list[Violation] = []
        dropped = 0

        for v in violations:
            if v.rule_id not in exact_rules:
                validated.append(v)
                continue

            pattern = RuleRegistry.get_exact_pattern(v.rule_id)
            if pattern is None:
                validated.append(v)
                continue

            # 检查 LLM 报告的原始文本是否包含关键词
            text_to_check = v.original_text or ""
            if pattern.search(text_to_check):
                validated.append(v)
            else:
                # 正则未命中，回退拼音匹配
                pinyin_patterns = RuleRegistry.get_pinyin_patterns(v.rule_id)
                if pinyin_patterns and self._pinyin_match(text_to_check, pinyin_patterns):
                    validated.append(v)
                else:
                    dropped += 1
                    logger.info(
                        "ExactMatchValidator: dropped violation rule_id=%d "
                        "(keyword not found in original_text: %r)",
                        v.rule_id,
                        text_to_check[:100],
                    )

        # 补充扫描：检查全文本中的关键词命中，LLM 可能遗漏
        reported_rules = {v.rule_id for v in validated}
        for rule_id, rule in exact_rules.items():
            if rule_id in reported_rules:
                continue

            pattern = RuleRegistry.get_exact_pattern(rule_id)
            if pattern is None:
                continue

            match = pattern.search(full_text)
            if match:
                validated.append(
                    Violation(
                        rule_id=rule_id,
                        rule_content=rule.content,
                        timestamp="00:00",
                        timestamp_ms=0,
                        end_ms=0,
                        speaker="",
                        original_text=_extract_context(full_text, match.start(), 80),
                        reason=f"精确匹配检测到禁止用语「{match.group()}」",
                        severity=rule.severity_default,
                        confidence=1.0,
                        source="transcript",
                    )
                )
                logger.info(
                    "ExactMatchValidator: added missing violation rule_id=%d "
                    "(keyword %r found in full text)",
                    rule_id,
                    match.group(),
                )
                continue

            # 正则未命中，回退拼音扫描全文
            pinyin_patterns = RuleRegistry.get_pinyin_patterns(rule_id)
            if not pinyin_patterns:
                continue
            matched_kw = self._pinyin_match(full_text, pinyin_patterns)
            if matched_kw:
                validated.append(
                    Violation(
                        rule_id=rule_id,
                        rule_content=rule.content,
                        timestamp="00:00",
                        timestamp_ms=0,
                        end_ms=0,
                        speaker="",
                        original_text=_extract_context(full_text, 0, 80),
                        reason=f"拼音匹配检测到禁止用语同音字（对应「{matched_kw}」）",
                        severity=rule.severity_default,
                        confidence=0.95,
                        source="transcript",
                    )
                )
                logger.info(
                    "ExactMatchValidator: added missing violation rule_id=%d "
                    "(pinyin match for keyword %r in full text)",
                    rule_id,
                    matched_kw,
                )

        if dropped:
            logger.info("ExactMatchValidator: dropped %d false positives", dropped)
        return validated

    @staticmethod
    def _pinyin_match(
        text: str, pinyin_patterns: list[tuple[str, str]]
    ) -> str | None:
        """对文本做拼音匹配，返回命中的 keyword 原文或 None。"""
        if not text:
            return None
        text_pinyin = _text_to_pinyin(text)
        for kw, kw_pinyin in pinyin_patterns:
            if _pinyin_contains(text_pinyin, kw_pinyin, len(kw)) is not None:
                return kw
        return None


class DeduplicationFilter:
    """同 rule_id 且时间差 < window_ms 的合并，保留最高 confidence。"""

    def __init__(self, window_ms: int = 30000) -> None:
        self._window_ms = window_ms

    def apply(self, violations: list[Violation]) -> list[Violation]:
        if not violations:
            return violations

        # 按 rule_id + timestamp_ms 排序
        sorted_vs = sorted(violations, key=lambda v: (v.rule_id, v.timestamp_ms))
        result: list[Violation] = []
        prev: Violation | None = None

        for v in sorted_vs:
            if (
                prev is not None
                and prev.rule_id == v.rule_id
                and abs(v.timestamp_ms - prev.timestamp_ms) < self._window_ms
            ):
                # 合并：保留 confidence 更高的
                if v.confidence > prev.confidence:
                    result[-1] = v
                continue
            result.append(v)
            prev = v

        deduped = len(violations) - len(result)
        if deduped:
            logger.info(
                "DeduplicationFilter: merged %d duplicates (window=%dms)",
                deduped,
                self._window_ms,
            )
        return result


class EvidenceEnricher:
    """填充 evidence_url、evidence_text、source 字段。"""

    def apply(
        self,
        violations: list[Violation],
        ocr_results: list[dict] | None = None,
    ) -> list[Violation]:
        if not ocr_results:
            return violations

        for v in violations:
            if v.evidence_text or v.source != "transcript":
                continue

            # 查找时间最接近的 OCR 记录作为辅助证据
            best_ocr = _find_nearest_ocr(v.timestamp_ms, ocr_results)
            if best_ocr:
                v.evidence_text = best_ocr.get("text", "")
                frame_path = best_ocr.get("frame_path", "")
                if frame_path:
                    v.evidence_url = os.path.basename(frame_path)

        return violations


def run_filters(
    violations: list[Violation],
    *,
    rules: list[StructuredRule] | None = None,
    full_text: str = "",
    ocr_results: list[dict] | None = None,
    confidence_threshold: float = 0.7,
    dedup_window_ms: int = 30000,
) -> list[Violation]:
    """按顺序执行全部过滤器。"""
    result = ConfidenceFilter(confidence_threshold).apply(violations)

    if rules:
        result = ExactMatchValidator().apply(result, rules, full_text)

    result = DeduplicationFilter(dedup_window_ms).apply(result)
    result = EvidenceEnricher().apply(result, ocr_results)

    # 恢复时间排序
    result.sort(key=lambda v: v.timestamp_ms)
    return result


# ------------------------------------------------------------------ #
#  辅助函数
# ------------------------------------------------------------------ #


def _text_to_pinyin(text: str) -> list[str]:
    """将中文文本转为拼音音节列表（小写，无声调）。"""
    return lazy_pinyin(text)


def _pinyin_contains(
    text_pinyin: list[str], keyword_pinyin: str, keyword_len: int
) -> int | None:
    """在拼音列表上做定长滑动窗口匹配。

    Args:
        text_pinyin: 全文拼音音节列表
        keyword_pinyin: keyword 拼音字符串（空格分隔）
        keyword_len: keyword 字符数（等于拼音音节数）

    Returns:
        匹配起始位置（字符级），或 None
    """
    if len(text_pinyin) < keyword_len:
        return None
    for i in range(len(text_pinyin) - keyword_len + 1):
        window = " ".join(text_pinyin[i : i + keyword_len])
        if window == keyword_pinyin:
            return i
    return None


def _extract_context(text: str, pos: int, radius: int = 80) -> str:
    """从文本中提取 pos 附近的上下文片段。"""
    start = max(0, pos - radius)
    end = min(len(text), pos + radius)
    return text[start:end]


def _find_nearest_ocr(
    timestamp_ms: int, ocr_results: list[dict], margin_ms: int = 10000
) -> dict | None:
    """查找时间最接近的 OCR 记录。"""
    best: dict | None = None
    best_diff = margin_ms + 1

    for ocr in ocr_results:
        ocr_ms = ocr.get("timestamp_ms", 0)
        diff = abs(ocr_ms - timestamp_ms)
        if diff < best_diff:
            best_diff = diff
            best = ocr

    return best
