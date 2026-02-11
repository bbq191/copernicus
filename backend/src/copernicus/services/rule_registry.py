"""结构化规则注册表

为 13 条保险产说会合规规则提供结构化元数据，替代纯文本注入。
每条规则明确 category / check_mode / evidence_sources / keywords，
使审核 prompt 精准匹配，减少误报。

Author: afu
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from pypinyin import lazy_pinyin

from copernicus.schemas.compliance import ComplianceRule

RuleCategory = Literal[
    "forbidden_phrase",  # 禁止用语
    "behavioral",  # 行为规范
    "document",  # 文件/资料要求
    "visual_check",  # 视觉检查
]

CheckMode = Literal[
    "exact",  # 精确关键词匹配（Python 正则预检）
    "semantic",  # 语义审核（LLM 判定）
    "visual",  # 视觉审核（需 OCR 证据）
]


@dataclass(frozen=True)
class StructuredRule:
    """一条带完整元数据的合规规则。"""

    id: int
    title: str
    content: str
    category: RuleCategory
    check_mode: CheckMode
    evidence_sources: list[str] = field(default_factory=lambda: ["transcript"])
    keywords: list[str] = field(default_factory=list)
    description: str = ""
    severity_default: Literal["high", "medium", "low"] = "medium"


# ------------------------------------------------------------------ #
#  13 条保险产说会合规规则的内置注册表
# ------------------------------------------------------------------ #

_BUILTIN_RULES: list[StructuredRule] = [
    StructuredRule(
        id=1,
        title="如实告知",
        content="讲师应提醒投保人如实告知健康状况和相关信息",
        category="behavioral",
        check_mode="semantic",
        evidence_sources=["transcript"],
        description=(
            "检查讲师是否在产说会中提醒投保人如实告知。"
            "仅当完全未提及告知义务时才标记违规；"
            "简略提及不构成违规。"
        ),
        severity_default="medium",
    ),
    StructuredRule(
        id=2,
        title="风险提示",
        content="讲师应充分提示保险产品的风险和免责条款",
        category="behavioral",
        check_mode="semantic",
        evidence_sources=["transcript"],
        description=(
            "检查讲师是否提及产品风险和免责条款。"
            "仅当完全未提及风险/免责时才标记违规；"
            "合规的风险提示内容本身不构成违规。"
        ),
        severity_default="medium",
    ),
    StructuredRule(
        id=3,
        title="产品条款展示",
        content="产说会现场应展示产品条款和保险合同重要内容",
        category="visual_check",
        check_mode="visual",
        evidence_sources=["ocr"],
        description=(
            "检查现场是否通过屏幕/投影展示了产品条款。"
            "需要 OCR 证据支持，纯语音转录无法判定。"
            "如无 OCR 数据则跳过此规则。"
        ),
        severity_default="medium",
    ),
    StructuredRule(
        id=4,
        title="全程双录",
        content="产说会全程应进行录音录像",
        category="behavioral",
        check_mode="semantic",
        evidence_sources=["transcript"],
        description=(
            "检查是否提及录音录像安排。"
            "此规则侧重流程合规，仅当明确表示未录制时才标记违规。"
        ),
        severity_default="high",
    ),
    StructuredRule(
        id=5,
        title="不得夸大收益",
        content="不得夸大或变相夸大保险产品收益，不得承诺保证收益",
        category="forbidden_phrase",
        check_mode="semantic",
        evidence_sources=["transcript", "ocr"],
        keywords=["保证收益", "稳赚", "只赚不赔", "翻倍", "年化收益率"],
        description=(
            "检查是否夸大产品收益或承诺保证收益。"
            "注意：产品参数的客观陈述（如投保年龄、费率、保额）不是'夸大'；"
            "保单利益演示中标注'假设投资回报率'属于合规披露，不是承诺收益；"
            "仅当讲师做出超越合同条款的收益承诺时才标记违规。"
        ),
        severity_default="high",
    ),
    StructuredRule(
        id=6,
        title="不得诋毁同业",
        content="不得诋毁、贬低其他保险公司或其产品",
        category="forbidden_phrase",
        check_mode="semantic",
        evidence_sources=["transcript"],
        keywords=["垃圾公司", "骗人", "倒闭"],
        description=(
            "检查是否贬低或诋毁竞争对手。"
            "客观对比产品特征不构成诋毁；"
            "仅当使用贬义词汇攻击其他公司或产品时才标记违规。"
        ),
        severity_default="high",
    ),
    StructuredRule(
        id=7,
        title="信息披露完整",
        content="产说会材料应包含完整的产品信息和公司信息披露",
        category="visual_check",
        check_mode="visual",
        evidence_sources=["ocr"],
        description=(
            "检查展示材料是否包含完整的产品和公司信息。"
            "需要 OCR 证据支持，纯语音转录无法判定。"
            "如无 OCR 数据则跳过此规则。"
        ),
        severity_default="low",
    ),
    StructuredRule(
        id=8,
        title="不得误导",
        content="不得以任何方式误导投保人，不得隐瞒重要信息",
        category="forbidden_phrase",
        check_mode="semantic",
        evidence_sources=["transcript", "ocr"],
        description=(
            "检查是否存在误导投保人或隐瞒重要信息的行为。"
            "正常的产品介绍和条款解读不构成误导；"
            "仅当故意曲解条款含义或隐瞒关键限制条件时才标记违规。"
        ),
        severity_default="high",
    ),
    StructuredRule(
        id=9,
        title="不得夸大经营成果",
        content="不得夸大公司经营成果或使用未经核实的数据",
        category="forbidden_phrase",
        check_mode="semantic",
        evidence_sources=["transcript", "ocr"],
        keywords=["行业第一", "最大", "最强", "最好"],
        description=(
            "检查是否夸大公司经营成果。"
            "注意：产品参数的客观陈述（如投保年龄范围、保障期限）不是'夸大经营成果'；"
            "合同条款中载明的保额、费率等属于产品事实，不涉及经营成果；"
            "仅当使用无依据的排名、未经核实的统计数据来美化公司时才标记违规。"
        ),
        severity_default="high",
    ),
    StructuredRule(
        id=10,
        title="讲师资质",
        content="主讲人应具备相应的保险从业资格",
        category="behavioral",
        check_mode="semantic",
        evidence_sources=["transcript"],
        description=(
            "检查讲师是否展示或提及从业资格。"
            "未提及资格不一定违规（可能在会前已验证）；"
            "仅当有证据表明讲师无资质时才标记违规。"
        ),
        severity_default="low",
    ),
    StructuredRule(
        id=11,
        title="适当性义务",
        content="应根据投保人需求推荐适合的产品，不得强制搭售",
        category="behavioral",
        check_mode="semantic",
        evidence_sources=["transcript"],
        description=(
            "检查是否根据客户需求推荐产品。"
            "正常的产品推荐话术不构成违规；"
            "仅当强制搭售或完全不考虑客户需求时才标记违规。"
        ),
        severity_default="medium",
    ),
    StructuredRule(
        id=12,
        title="禁止混淆概念",
        content="不得将保险产品与银行存款、基金等混淆，不得使用存取、利息、本金等概念",
        category="forbidden_phrase",
        check_mode="exact",
        evidence_sources=["transcript", "ocr"],
        keywords=[
            "存取", "利息", "本金", "存款", "储蓄", "存钱", "取钱", "利率",
        ],
        description=(
            "检查是否将保险与银行存款混淆。"
            "此规则使用精确匹配：文本中出现禁止关键词即违规。"
            "同音字替代也应识别（如'保种'可能是'保证'，'犁息'可能是'利息'）。"
        ),
        severity_default="high",
    ),
    StructuredRule(
        id=13,
        title="禁止不当用语",
        content="不得使用保证、保种水平、零风险等不当用语描述保险产品",
        category="forbidden_phrase",
        check_mode="exact",
        evidence_sources=["transcript", "ocr"],
        keywords=[
            "保种水平", "保证水平", "零风险", "无风险",
            "绝对安全", "百分百", "100%赔付",
        ],
        description=(
            "检查是否使用禁止用语描述保险产品。"
            "此规则使用精确匹配：文本中出现禁止关键词即违规。"
            "注意同音字替代（如'保种'='保证'）。"
        ),
        severity_default="high",
    ),
]

# 快速索引：rule_id -> StructuredRule
_BUILTIN_INDEX: dict[int, StructuredRule] = {r.id: r for r in _BUILTIN_RULES}

# 内容匹配词组：用于将 CSV 规则按内容（而非 ID）映射到内置规则
_MATCH_TOKENS: dict[int, list[str]] = {
    1:  ["如实告知", "告知义务", "健康状况"],
    2:  ["风险提示", "免责条款"],
    3:  ["条款展示", "条款", "统一印制", "宣传材料"],
    4:  ["全程双录", "双录", "录音录像", "摄录"],
    5:  ["夸大收益", "保证收益", "承诺收益", "变相夸大"],
    6:  ["诋毁同业", "诋毁", "贬低"],
    7:  ["信息披露", "课件文件名", "定稿日期"],
    8:  ["虚假陈述", "误导宣传", "误导", "不实对比"],
    9:  ["保单利益", "分红", "经营成果", "万能险", "投资收益"],
    10: ["讲师资质", "从业资格", "认证资格", "师资", "资料归档"],
    11: ["适当性", "搭售", "主讲人"],
    12: ["存取", "利息", "本金", "混淆", "比率简单对比"],
    13: ["保种水平", "保证水平", "零风险", "不允许出现"],
}

# exact 模式规则的预编译正则
_EXACT_PATTERNS: dict[int, re.Pattern[str]] = {}
for _r in _BUILTIN_RULES:
    if _r.check_mode == "exact" and _r.keywords:
        _EXACT_PATTERNS[_r.id] = re.compile("|".join(re.escape(k) for k in _r.keywords))

# exact 模式规则的拼音索引：{rule_id: [(keyword原文, "bao zheng shui ping"), ...]}
_EXACT_PINYIN: dict[int, list[tuple[str, str]]] = {}
for _r in _BUILTIN_RULES:
    if _r.check_mode == "exact" and _r.keywords:
        _EXACT_PINYIN[_r.id] = [
            (kw, " ".join(lazy_pinyin(kw))) for kw in _r.keywords
        ]


class RuleRegistry:
    """将 CSV 解析的 ComplianceRule 匹配为 StructuredRule。"""

    def __init__(self) -> None:
        self._index: dict[int, StructuredRule] = dict(_BUILTIN_INDEX)

    def enrich(self, rules: list[ComplianceRule]) -> list[StructuredRule]:
        """将 ComplianceRule 列表转换为 StructuredRule 列表。

        匹配策略：按规则内容关键词匹配内置规则，而非按 ID 盲匹配。
        这样即使 CSV 编号与内置规则不一致，也能正确映射。
        未匹配的规则 fallback 为默认 semantic 模式。
        """
        result: list[StructuredRule] = []
        for rule in rules:
            builtin = self._match_by_content(rule.content)
            if builtin is not None:
                enriched = StructuredRule(
                    id=builtin.id,
                    title=builtin.title,
                    content=rule.content,
                    category=builtin.category,
                    check_mode=builtin.check_mode,
                    evidence_sources=list(builtin.evidence_sources),
                    keywords=list(builtin.keywords),
                    description=builtin.description,
                    severity_default=builtin.severity_default,
                )
            else:
                enriched = StructuredRule(
                    id=rule.id,
                    title=f"规则{rule.id}",
                    content=rule.content,
                    category="behavioral",
                    check_mode="semantic",
                    evidence_sources=["transcript"],
                    description=(
                        "基于规则原文进行语义审核。"
                        "仅当文本明确违反此规则要求时才标记违规；"
                        "客观事实陈述不构成违规。"
                    ),
                    severity_default="medium",
                )
            result.append(enriched)
        return result

    @staticmethod
    def _match_by_content(content: str) -> StructuredRule | None:
        """按内容关键词匹配最佳内置规则。

        对每条内置规则计算命中 token 数，选最高分且 > 0 的。
        """
        best_id: int | None = None
        best_score = 0
        for rule_id, tokens in _MATCH_TOKENS.items():
            score = sum(1 for t in tokens if t in content)
            if score > best_score:
                best_score = score
                best_id = rule_id
        if best_id is not None:
            return _BUILTIN_INDEX[best_id]
        return None

    @staticmethod
    def get_exact_pattern(rule_id: int) -> re.Pattern[str] | None:
        """获取 exact 模式规则的预编译正则表达式。"""
        return _EXACT_PATTERNS.get(rule_id)

    @staticmethod
    def get_pinyin_patterns(rule_id: int) -> list[tuple[str, str]] | None:
        """获取 exact 模式规则的拼音索引。

        返回 [(keyword原文, keyword拼音字符串), ...] 或 None。
        """
        return _EXACT_PINYIN.get(rule_id)

    @staticmethod
    def group_by_source(
        rules: list[StructuredRule],
    ) -> dict[str, list[StructuredRule]]:
        """将规则按 evidence_sources 分组。

        返回 3 个组：
        - "transcript": 仅需转录文本的规则
        - "ocr": 仅需 OCR 的规则
        - "mixed": 需要转录 + OCR 双源的规则
        """
        groups: dict[str, list[StructuredRule]] = {
            "transcript": [],
            "ocr": [],
            "mixed": [],
        }
        for r in rules:
            sources = set(r.evidence_sources)
            if sources == {"transcript"}:
                groups["transcript"].append(r)
            elif sources == {"ocr"}:
                groups["ocr"].append(r)
            else:
                groups["mixed"].append(r)
        return groups
