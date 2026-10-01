"""Phase 3 认知审计功能验证

覆盖场景：
  1. 精确匹配验证（ExactMatchValidator）
  2. 误报回归测试（CoT prompt + 置信度过滤）
  3. OCR 融合测试（时间对齐 + prompt 注入）
  4. 置信度过滤测试
  5. 去重过滤测试
  6. 规则分组测试
  7. 向后兼容测试（纯音频，无 OCR）
  8. reasoning 字段透传

Author: afu
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from copernicus.config import Settings
from copernicus.exceptions import ComplianceError
from copernicus.schemas.compliance import ComplianceRule, Violation
from copernicus.services.compliance import (
    ComplianceService,
    _align_ocr_to_chunk,
    _build_vision_summary,
    _parse_violations,
)
from copernicus.services.compliance_filters import (
    ConfidenceFilter,
    DeduplicationFilter,
    EvidenceEnricher,
    ExactMatchValidator,
    run_filters,
)
from copernicus.services.llm import ChatResponse
from copernicus.services.rule_registry import RuleRegistry


# ------------------------------------------------------------------ #
#  Fixtures
# ------------------------------------------------------------------ #


@pytest.fixture
def mock_settings() -> Settings:
    return Settings(
        llm_api_key="test-key",
        llm_base_url="http://localhost:11434",
        llm_model_name="test-model",
        compliance_confidence_threshold=0.7,
        compliance_dedup_window_ms=30000,
        compliance_group_by_source=True,
        compliance_ocr_margin_ms=5000,
    )


@pytest.fixture
def service(mock_client: MagicMock, mock_settings: Settings) -> ComplianceService:
    return ComplianceService(mock_client, mock_settings)


@pytest.fixture
def registry() -> RuleRegistry:
    return RuleRegistry()


@pytest.fixture
def sample_entries() -> list[dict]:
    return [
        {
            "timestamp": "00:30",
            "timestamp_ms": 30000,
            "end_ms": 45000,
            "speaker": "讲师",
            "text_corrected": "这款产品的投保年龄是8到65岁，保障期限为终身。",
        },
        {
            "timestamp": "01:00",
            "timestamp_ms": 60000,
            "end_ms": 75000,
            "speaker": "讲师",
            "text_corrected": "我们公司去年的保费收入创历史新高，是行业第一。",
        },
        {
            "timestamp": "01:30",
            "timestamp_ms": 90000,
            "end_ms": 105000,
            "speaker": "讲师",
            "text_corrected": "这个产品就像存钱一样，利息比银行高，本金绝对安全。",
        },
    ]


# ------------------------------------------------------------------ #
#  1. 精确匹配验证
# ------------------------------------------------------------------ #


class TestExactMatchValidator:
    def test_drops_false_positive_without_keyword(self, registry: RuleRegistry):
        """LLM 报告 rule_id=12 但 original_text 中无禁止关键词 -> 丢弃"""
        rules = registry.enrich([ComplianceRule(id=12, content="禁止混淆概念")])
        vs = [
            Violation(
                rule_id=12,
                rule_content="禁止混淆概念",
                reason="使用了投保年龄",
                confidence=0.9,
                original_text="投保年龄8到65岁",
            ),
        ]
        result = ExactMatchValidator().apply(vs, rules, "投保年龄8到65岁")
        assert len(result) == 0

    def test_keeps_true_positive_with_keyword(self, registry: RuleRegistry):
        """original_text 中包含禁止关键词 -> 保留"""
        rules = registry.enrich([ComplianceRule(id=12, content="禁止混淆概念")])
        vs = [
            Violation(
                rule_id=12,
                rule_content="禁止混淆概念",
                reason="使用了本金",
                confidence=0.9,
                original_text="本金绝对安全",
            ),
        ]
        result = ExactMatchValidator().apply(vs, rules, "本金绝对安全")
        assert len(result) == 1
        assert result[0].original_text == "本金绝对安全"

    def test_supplements_missed_violation(self, registry: RuleRegistry):
        """LLM 遗漏但全文中存在禁止关键词 -> 补充添加"""
        rules = registry.enrich([ComplianceRule(id=12, content="禁止混淆概念")])
        result = ExactMatchValidator().apply(
            [], rules, "这个产品就像存钱一样，利息比银行高"
        )
        assert len(result) == 1
        assert result[0].rule_id == 12
        assert result[0].confidence == 1.0

    def test_passthrough_non_exact_rules(self, registry: RuleRegistry):
        """非 exact 模式的规则不受影响"""
        rules = registry.enrich([ComplianceRule(id=5, content="不得夸大收益")])
        vs = [
            Violation(
                rule_id=5,
                rule_content="不得夸大收益",
                reason="夸大了",
                confidence=0.8,
                original_text="收益很高",
            ),
        ]
        result = ExactMatchValidator().apply(vs, rules, "收益很高")
        assert len(result) == 1

    def test_homophone_variants(self, registry: RuleRegistry):
        """ASR 同音字"保正水平"应通过拼音回退命中 rule 13。

        "保正水平"(bao zheng shui ping) 与 "保证水平" 拼音完全一致，
        但不在 keywords 列表中，正则匹配不到，拼音回退路径应保留该违规。
        """
        rules = registry.enrich([
            ComplianceRule(id=13, content="不得使用保证水平、零风险等不当用语"),
        ])
        vs = [
            Violation(
                rule_id=13,
                rule_content="禁止不当用语",
                reason="使用了保证水平的同音字变体",
                confidence=0.9,
                original_text="保正水平主要取决于保险公司实际经营成果",
            ),
        ]
        result = ExactMatchValidator().apply(
            vs, rules, "保正水平主要取决于保险公司实际经营成果"
        )
        assert len(result) == 1
        assert result[0].rule_id == 13

    def test_homophone_supplement(self, registry: RuleRegistry):
        """LLM 遗漏但全文含同音字"犁息" -> 拼音补充路径应添加违规"""
        rules = registry.enrich([
            ComplianceRule(id=12, content="不得使用存取、利息、本金等概念"),
        ])
        result = ExactMatchValidator().apply(
            [], rules, "这个产品的犁息比银行高"
        )
        assert len(result) == 1
        assert result[0].rule_id == 12

    def test_pinyin_novel_homophone(self, registry: RuleRegistry):
        """从未出现在 keywords 中的新同音字变体，验证拼音泛化能力。

        "笨金" 是 "本金" 的同音字变体，不在 keywords 列表中，
        但拼音匹配应能自动捕获。
        """
        rules = registry.enrich([
            ComplianceRule(id=12, content="不得使用存取、利息、本金等概念"),
        ])
        result = ExactMatchValidator().apply(
            [], rules, "这个产品笨金有保障"
        )
        assert len(result) == 1
        assert result[0].rule_id == 12

    def test_pinyin_no_false_positive(self, registry: RuleRegistry):
        """拼音不同不应误匹配："保证质量"不应命中"保证水平"。"""
        rules = registry.enrich([
            ComplianceRule(id=13, content="不得使用保证水平、零风险等不当用语"),
        ])
        vs = [
            Violation(
                rule_id=13,
                rule_content="禁止不当用语",
                reason="疑似不当用语",
                confidence=0.8,
                original_text="我们保证质量是最好的",
            ),
        ]
        result = ExactMatchValidator().apply(
            vs, rules, "我们保证质量是最好的"
        )
        # "保证质量"拼音与任何 rule 13 keyword 都不匹配，应被丢弃
        assert len(result) == 0


# ------------------------------------------------------------------ #
#  2. 误报回归测试
# ------------------------------------------------------------------ #


class TestFalsePositiveRegression:
    def test_objective_age_not_exaggeration(self):
        """'投保年龄8-65岁' + 规则9（不得夸大经营成果）不应误报。

        场景：LLM 返回空数组（新 prompt 的预期行为）。
        """
        raw = "[]"
        rules = [ComplianceRule(id=9, content="不得夸大经营成果")]
        violations = _parse_violations(raw, rules)
        assert violations == []

    def test_low_confidence_filtered(self):
        """LLM 仍然返回了误报但 confidence < 0.7 -> 被过滤器丢弃"""
        raw = json.dumps([{
            "rule_id": 9,
            "timestamp": "00:30",
            "timestamp_ms": 30000,
            "end_ms": 45000,
            "speaker": "讲师",
            "original_text": "投保年龄8到65岁",
            "reason": "涉及夸大",
            "severity": "medium",
            "confidence": 0.4,
        }])
        rules = [ComplianceRule(id=9, content="不得夸大经营成果")]
        violations = _parse_violations(raw, rules)
        assert len(violations) == 1
        filtered = ConfidenceFilter(0.7).apply(violations)
        assert len(filtered) == 0


# ------------------------------------------------------------------ #
#  3. OCR 融合测试
# ------------------------------------------------------------------ #


class TestOCRAlignment:
    def test_filters_by_time_range(self):
        """只保留与 chunk 时间范围重叠（含 margin）的 OCR 记录"""
        entries = [
            {"timestamp_ms": 60000, "end_ms": 90000, "text_corrected": "x"},
        ]
        ocr = [
            {"timestamp_ms": 10000, "text": "too early"},
            {"timestamp_ms": 55000, "text": "just in margin"},
            {"timestamp_ms": 70000, "text": "in range"},
            {"timestamp_ms": 200000, "text": "too late"},
        ]
        aligned = _align_ocr_to_chunk(entries, ocr, margin_ms=5000)
        texts = [r["text"] for r in aligned]
        assert "just in margin" in texts
        assert "in range" in texts
        assert "too early" not in texts
        assert "too late" not in texts

    def test_deduplicates_same_frame_text(self):
        """同帧同文本去重"""
        entries = [
            {"timestamp_ms": 60000, "end_ms": 90000, "text_corrected": "x"},
        ]
        ocr = [
            {"timestamp_ms": 70000, "text": "same text"},
            {"timestamp_ms": 70000, "text": "same text"},
            {"timestamp_ms": 70000, "text": "different text"},
        ]
        aligned = _align_ocr_to_chunk(entries, ocr, margin_ms=5000)
        assert len(aligned) == 2

    def test_empty_ocr_returns_empty(self):
        entries = [{"timestamp_ms": 0, "end_ms": 1000, "text_corrected": "x"}]
        assert _align_ocr_to_chunk(entries, [], margin_ms=5000) == []
        assert _align_ocr_to_chunk(entries, None, margin_ms=5000) == []

    def test_sorted_by_timestamp(self):
        entries = [
            {"timestamp_ms": 0, "end_ms": 100000, "text_corrected": "x"},
        ]
        ocr = [
            {"timestamp_ms": 50000, "text": "later"},
            {"timestamp_ms": 10000, "text": "earlier"},
        ]
        aligned = _align_ocr_to_chunk(entries, ocr, margin_ms=5000)
        assert aligned[0]["text"] == "earlier"
        assert aligned[1]["text"] == "later"


class TestVisionSummary:
    """画面人脸证据摘要：覆盖率 + 较长缺失时段，短暂切镜头不计入。"""

    def test_no_events_or_unknown_duration_returns_none(self):
        assert _build_vision_summary(None, 100000) is None
        assert _build_vision_summary([], 100000) is None
        assert _build_vision_summary([{"event_type": "face_missing", "start_ms": 0, "end_ms": 10000}], 0) is None

    def test_full_coverage_has_no_missing_events(self):
        events = [{"event_type": "face_detected", "start_ms": 0, "end_ms": 100000, "confidence": 0.9}]
        assert _build_vision_summary(events, 100000) is None

    def test_short_gap_counted_in_coverage_but_not_listed(self):
        """短暂切镜头（< 60s）计入覆盖率百分比，但不单独列出时段，避免误导 LLM 过度判定。"""
        events = [
            {"event_type": "face_detected", "start_ms": 0, "end_ms": 50000},
            {"event_type": "face_missing", "start_ms": 50000, "end_ms": 60000},  # 10s，短
            {"event_type": "face_detected", "start_ms": 60000, "end_ms": 100000},
        ]
        summary = _build_vision_summary(events, 100000)
        assert "90%" in summary
        assert "~" not in summary  # 没有列出具体时段

    def test_long_gap_is_listed_with_timestamps(self):
        events = [
            {"event_type": "face_detected", "start_ms": 0, "end_ms": 60000},
            {"event_type": "face_missing", "start_ms": 60000, "end_ms": 180000},  # 120s，长
        ]
        summary = _build_vision_summary(events, 180000)
        assert "01:00 ~ 03:00" in summary
        assert "33%" in summary

    def test_long_gaps_are_capped_and_sorted_by_time(self):
        events = [
            {"event_type": "face_missing", "start_ms": i * 1_000_000, "end_ms": i * 1_000_000 + 70000}
            for i in range(8)
        ]
        summary = _build_vision_summary(events, 8_000_000)
        lines = [ln for ln in summary.splitlines() if ln.startswith("-")]
        assert len(lines) == 5  # _VISION_SUMMARY_MAX_GAPS
        assert lines == sorted(lines)  # 按时间先后排列，不是按时长


# ------------------------------------------------------------------ #
#  4. 置信度过滤测试
# ------------------------------------------------------------------ #


class TestConfidenceFilter:
    def test_drops_below_threshold(self):
        vs = [
            Violation(rule_id=1, rule_content="r", reason="r", confidence=0.3),
            Violation(rule_id=2, rule_content="r", reason="r", confidence=0.7),
            Violation(rule_id=3, rule_content="r", reason="r", confidence=0.95),
        ]
        result = ConfidenceFilter(0.7).apply(vs)
        assert len(result) == 2
        assert all(v.confidence >= 0.7 for v in result)

    def test_keeps_exactly_at_threshold(self):
        vs = [Violation(rule_id=1, rule_content="r", reason="r", confidence=0.7)]
        result = ConfidenceFilter(0.7).apply(vs)
        assert len(result) == 1

    def test_empty_input(self):
        assert ConfidenceFilter(0.7).apply([]) == []


# ------------------------------------------------------------------ #
#  5. 去重过滤测试
# ------------------------------------------------------------------ #


class TestDeduplicationFilter:
    def test_merges_same_rule_within_window(self):
        vs = [
            Violation(rule_id=1, rule_content="r", reason="a", confidence=0.8, timestamp_ms=1000),
            Violation(rule_id=1, rule_content="r", reason="b", confidence=0.9, timestamp_ms=5000),
        ]
        result = DeduplicationFilter(30000).apply(vs)
        assert len(result) == 1
        assert result[0].confidence == 0.9  # 保留更高的

    def test_keeps_different_rules(self):
        vs = [
            Violation(rule_id=1, rule_content="r", reason="a", confidence=0.8, timestamp_ms=1000),
            Violation(rule_id=2, rule_content="r", reason="b", confidence=0.8, timestamp_ms=1000),
        ]
        result = DeduplicationFilter(30000).apply(vs)
        assert len(result) == 2

    def test_keeps_same_rule_outside_window(self):
        vs = [
            Violation(rule_id=1, rule_content="r", reason="a", confidence=0.8, timestamp_ms=1000),
            Violation(rule_id=1, rule_content="r", reason="b", confidence=0.8, timestamp_ms=50000),
        ]
        result = DeduplicationFilter(30000).apply(vs)
        assert len(result) == 2


# ------------------------------------------------------------------ #
#  6. 规则分组测试
# ------------------------------------------------------------------ #


class TestRuleGrouping:
    def test_groups_correctly(self, registry: RuleRegistry):
        rules = registry.enrich([
            ComplianceRule(id=1, content="如实告知"),       # transcript only
            ComplianceRule(id=3, content="条款展示"),       # ocr only
            ComplianceRule(id=4, content="全程双录"),       # mixed (transcript + vision)
            ComplianceRule(id=5, content="不得夸大收益"),    # mixed (transcript + ocr)
            ComplianceRule(id=12, content="禁止混淆概念"),   # mixed
        ])
        groups = RuleRegistry.group_by_source(rules)
        assert len(groups["transcript"]) == 1
        assert groups["transcript"][0].id == 1
        assert len(groups["ocr"]) == 1
        assert groups["ocr"][0].id == 3
        assert len(groups["mixed"]) == 3
        mixed_ids = {r.id for r in groups["mixed"]}
        assert mixed_ids == {4, 5, 12}

    def test_double_recording_rule_declares_vision_evidence(self, registry: RuleRegistry):
        rules = registry.enrich([ComplianceRule(id=4, content="全程双录")])
        assert set(rules[0].evidence_sources) == {"transcript", "vision"}

    def test_fallback_rule_in_transcript_group(self, registry: RuleRegistry):
        """未匹配的自定义规则应归入 transcript 组"""
        rules = registry.enrich([ComplianceRule(id=99, content="自定义规则")])
        groups = RuleRegistry.group_by_source(rules)
        assert len(groups["transcript"]) == 1
        assert groups["transcript"][0].id == 99

    def test_content_based_matching(self, registry: RuleRegistry):
        """CSV id=1 内容为"审批报备"不应匹配内置 id=1（如实告知）。

        内容匹配优先于 ID 匹配，无匹配 token 时走 fallback。
        """
        rules = registry.enrich([ComplianceRule(id=1, content="审批报备相关要求")])
        assert len(rules) == 1
        r = rules[0]
        # fallback: 没有任何 _MATCH_TOKENS 命中
        assert r.check_mode == "semantic"
        assert "如实告知" not in r.description
        assert "基于规则原文" in r.description

    def test_csv_with_different_numbering(self, registry: RuleRegistry):
        """模拟 CSV 编号与内置规则不一致的场景。

        CSV rule_id=3 内容含"存取利息本金"应匹配内置 id=12（禁止混淆概念），
        CSV rule_id=5 内容含"保证水平零风险"应匹配内置 id=13（禁止不当用语）。
        """
        rules = registry.enrich([
            ComplianceRule(id=3, content="不得使用存取、利息、本金等概念"),
            ComplianceRule(id=5, content="不得使用保证水平、零风险等不当用语"),
        ])
        assert len(rules) == 2
        # CSV id=3 -> 内置 id=12
        assert rules[0].id == 12
        assert rules[0].check_mode == "exact"
        assert "存取" in rules[0].keywords
        # CSV id=5 -> 内置 id=13
        assert rules[1].id == 13
        assert rules[1].check_mode == "exact"
        assert "保种水平" in rules[1].keywords


class TestFromCustomRules:
    def _custom(self, **over):
        from copernicus.schemas.compliance import CustomRule

        fields = {
            "id": 1000,
            "title": "自定义规则",
            "content": "不得承诺保本",
            "category": "forbidden_phrase",
            "check_mode": "exact",
            "evidence_sources": ["transcript"],
            "keywords": ["保本"],
            "description": "",
            "severity_default": "high",
            "enabled": True,
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
        fields.update(over)
        return CustomRule(**fields)

    def test_converts_one_to_one_without_content_matching(self):
        structured = RuleRegistry.from_custom_rules([self._custom()])
        assert len(structured) == 1
        r = structured[0]
        assert (r.id, r.category, r.check_mode, r.keywords) == (1000, "forbidden_phrase", "exact", ["保本"])
        assert r.severity_default == "high"

    def test_disabled_rules_are_excluded(self):
        structured = RuleRegistry.from_custom_rules([self._custom(enabled=False)])
        assert structured == []


# ------------------------------------------------------------------ #
#  7. 向后兼容测试（无 OCR）
# ------------------------------------------------------------------ #


class TestBackwardCompatibility:
    @pytest.mark.asyncio
    async def test_audit_without_ocr(
        self, service: ComplianceService, mock_client: MagicMock
    ):
        """纯音频任务（无 OCR），audit() 行为与之前一致"""
        mock_client.chat = AsyncMock(
            return_value=ChatResponse(content="[]", model="test-model")
        )
        rules = [ComplianceRule(id=1, content="如实告知")]
        entries = [
            {
                "timestamp": "00:30",
                "timestamp_ms": 30000,
                "end_ms": 45000,
                "speaker": "讲师",
                "text_corrected": "请您如实告知健康状况。",
            },
        ]
        report = await service.audit(rules, entries)
        assert report.total_rules == 1
        assert report.violations == []
        assert report.summary == "审核完成，未发现违规内容。"
        assert report.compliance_score == 100.0

    @pytest.mark.asyncio
    async def test_audit_with_violations(
        self, service: ComplianceService, mock_client: MagicMock
    ):
        """LLM 返回违规时，正确解析并通过过滤器"""
        llm_output = json.dumps([{
            "rule_id": 12,
            "timestamp": "01:30",
            "timestamp_ms": 90000,
            "end_ms": 105000,
            "speaker": "讲师",
            "original_text": "利息比银行高，本金绝对安全",
            "reason": "将保险与银行存款混淆，使用了禁止词汇'利息''本金'",
            "reasoning": "第一步：规则12禁止使用存取、利息、本金等概念...",
            "severity": "high",
            "confidence": 0.95,
        }])
        # chat 被调用两次：一次 audit chunk，一次 summary
        mock_client.chat = AsyncMock(
            side_effect=[
                ChatResponse(content=llm_output, model="test-model"),
                ChatResponse(content="发现1条高风险违规。", model="test-model"),
            ]
        )
        rules = [ComplianceRule(id=12, content="禁止混淆概念")]
        entries = [
            {
                "timestamp": "01:30",
                "timestamp_ms": 90000,
                "end_ms": 105000,
                "speaker": "讲师",
                "text_corrected": "利息比银行高，本金绝对安全",
            },
        ]
        report = await service.audit(rules, entries)
        assert len(report.violations) >= 1
        v = report.violations[0]
        assert v.rule_id == 12
        assert v.confidence >= 0.7

    @pytest.mark.asyncio
    async def test_pre_structured_rules_skip_content_based_enrichment(
        self, service: ComplianceService, mock_client: MagicMock
    ):
        """规则库的 StructuredRule 已带完整元数据，audit() 不应再走模糊匹配。"""
        from copernicus.services.rule_registry import StructuredRule

        service._registry.enrich = MagicMock(side_effect=AssertionError("enrich() must not run"))
        mock_client.chat = AsyncMock(return_value=ChatResponse(content="[]", model="test-model"))

        structured = [StructuredRule(
            id=1000, title="自定义", content="不得承诺保本",
            category="forbidden_phrase", check_mode="exact", keywords=["保本"],
        )]
        entries = [{
            "timestamp": "00:30", "timestamp_ms": 30000, "end_ms": 45000,
            "speaker": "讲师", "text_corrected": "我们的产品非常安全。",
        }]

        report = await service.audit(structured, entries)
        assert report.total_rules == 1


class TestVisionWiring:
    """端到端验证：visual_events 真正进入 prompt，命中规则的违规被标记为 vision 来源。"""

    @pytest.mark.asyncio
    async def test_long_face_missing_gap_reaches_the_prompt_and_tags_the_violation(
        self, service: ComplianceService, mock_client: MagicMock
    ):
        llm_output = json.dumps([{
            "rule_id": 4,
            "timestamp": "01:00",
            "timestamp_ms": 60000,
            "end_ms": 60000,
            "speaker": "讲师",
            "original_text": "",
            "reason": "画面长时间未检测到人脸，双录可能不完整",
            "severity": "high",
            "confidence": 0.9,
        }])
        mock_client.chat = AsyncMock(
            side_effect=[
                ChatResponse(content=llm_output, model="test-model"),
                ChatResponse(content="发现1条高风险违规。", model="test-model"),
            ]
        )
        rules = [ComplianceRule(id=4, content="全程双录")]
        entries = [
            {
                "timestamp": "01:00", "timestamp_ms": 60000, "end_ms": 180000,
                "speaker": "讲师", "text_corrected": "接下来给大家介绍产品细节。",
            },
        ]
        visual_events = [{"event_type": "face_missing", "start_ms": 60000, "end_ms": 180000}]

        report = await service.audit(rules, entries, visual_events=visual_events)

        sent_prompt = mock_client.chat.call_args_list[0].kwargs["messages"][1]["content"]
        assert "【画面人脸检测证据】" in sent_prompt
        assert "01:00 ~ 03:00" in sent_prompt
        assert len(report.violations) == 1
        assert report.violations[0].source == "vision"

    @pytest.mark.asyncio
    async def test_no_visual_events_omits_the_evidence_block(
        self, service: ComplianceService, mock_client: MagicMock
    ):
        mock_client.chat = AsyncMock(return_value=ChatResponse(content="[]", model="test-model"))
        rules = [ComplianceRule(id=4, content="全程双录")]
        entries = [{"timestamp": "01:00", "timestamp_ms": 60000, "end_ms": 60000, "speaker": "讲师", "text_corrected": "x"}]

        await service.audit(rules, entries, visual_events=None)

        # 规则描述本身也提到"画面人脸检测证据"这个词，所以用证据摘要独有的措辞来判断证据块是否被注入
        sent_prompt = mock_client.chat.call_args_list[0].kwargs["messages"][1]["content"]
        assert "画面检测到人脸的时长占比" not in sent_prompt


# ------------------------------------------------------------------ #
#  8. reasoning 字段透传
# ------------------------------------------------------------------ #


class TestReasoningField:
    def test_reasoning_parsed_from_llm(self):
        """LLM 输出的 reasoning 字段应透传到 Violation"""
        raw = json.dumps([{
            "rule_id": 9,
            "timestamp": "01:00",
            "timestamp_ms": 60000,
            "end_ms": 75000,
            "speaker": "讲师",
            "original_text": "行业第一",
            "reason": "使用了未经核实的排名",
            "reasoning": "第一步：规则9禁止夸大经营成果；第二步：文本中出现'行业第一'；第三步：无数据支撑的排名声明违规",
            "severity": "high",
            "confidence": 0.9,
        }])
        rules = [ComplianceRule(id=9, content="不得夸大经营成果")]
        violations = _parse_violations(raw, rules)
        assert len(violations) == 1
        assert violations[0].reasoning is not None
        assert "行业第一" in violations[0].reasoning

    def test_reasoning_none_when_absent(self):
        """LLM 未输出 reasoning 时为 None"""
        raw = json.dumps([{
            "rule_id": 9,
            "timestamp": "01:00",
            "timestamp_ms": 60000,
            "end_ms": 75000,
            "speaker": "讲师",
            "original_text": "行业第一",
            "reason": "夸大",
            "severity": "high",
            "confidence": 0.9,
        }])
        rules = [ComplianceRule(id=9, content="不得夸大经营成果")]
        violations = _parse_violations(raw, rules)
        assert violations[0].reasoning is None


# ------------------------------------------------------------------ #
#  9. 完整过滤器链测试
# ------------------------------------------------------------------ #


class TestRunFilters:
    def test_full_pipeline(self, registry: RuleRegistry):
        """过滤器链：置信度过滤 -> 精确匹配验证 -> 去重 -> 证据填充"""
        rules = registry.enrich([
            ComplianceRule(id=9, content="不得夸大经营成果"),
            ComplianceRule(id=12, content="禁止混淆概念"),
        ])
        violations = [
            # 低置信度 -> 应被过滤
            Violation(
                rule_id=9, rule_content="不得夸大", reason="疑似",
                confidence=0.4, timestamp_ms=60000,
                original_text="收入创新高",
            ),
            # 高置信度 + exact rule 但无关键词 -> 应被 ExactMatchValidator 丢弃
            Violation(
                rule_id=12, rule_content="禁止混淆", reason="误报",
                confidence=0.9, timestamp_ms=30000,
                original_text="投保年龄8到65岁",
            ),
            # 高置信度 + 有关键词 -> 应保留
            Violation(
                rule_id=12, rule_content="禁止混淆", reason="含有本金",
                confidence=0.95, timestamp_ms=90000,
                original_text="本金绝对安全",
            ),
        ]
        result = run_filters(
            violations,
            rules=rules,
            full_text="投保年龄8到65岁 本金绝对安全",
            confidence_threshold=0.7,
            dedup_window_ms=30000,
        )
        # 只应保留 rule_id=12 的真正违规
        assert len(result) == 1
        assert result[0].rule_id == 12
        assert result[0].original_text == "本金绝对安全"


# ------------------------------------------------------------------ #
#  10. EvidenceEnricher 测试
# ------------------------------------------------------------------ #


class TestEvidenceEnricher:
    def test_enriches_with_nearest_ocr(self):
        vs = [
            Violation(
                rule_id=12, rule_content="r", reason="r",
                confidence=0.9, timestamp_ms=60000,
            ),
        ]
        ocr = [
            {"timestamp_ms": 55000, "text": "屏幕文字A", "frame_path": "/frames/001.jpg"},
            {"timestamp_ms": 200000, "text": "太远了", "frame_path": "/frames/099.jpg"},
        ]
        result = EvidenceEnricher().apply(vs, ocr)
        assert result[0].evidence_text == "屏幕文字A"
        assert result[0].evidence_url == "001.jpg"

    def test_no_ocr_no_change(self):
        vs = [
            Violation(rule_id=1, rule_content="r", reason="r", confidence=0.9),
        ]
        result = EvidenceEnricher().apply(vs, None)
        assert result[0].evidence_text is None

    def test_vision_sourced_violation_is_enriched_from_visual_events_not_ocr(self):
        vs = [
            Violation(
                rule_id=4, rule_content="全程双录", reason="r", confidence=0.9,
                timestamp_ms=65000, end_ms=65000, source="vision",
            ),
        ]
        ocr = [{"timestamp_ms": 65000, "text": "不应该用到这条", "frame_path": "/frames/ocr.jpg"}]
        visual_events = [
            {"event_type": "face_missing", "start_ms": 60000, "end_ms": 180000, "frame_path": "0007.jpg"},
        ]
        result = EvidenceEnricher().apply(vs, ocr, visual_events)
        assert result[0].evidence_text == "画面 01:00–03:00 未检测到人脸"
        assert result[0].evidence_url == "0007.jpg"

    def test_vision_source_without_overlapping_event_falls_back_to_nearest(self):
        vs = [
            Violation(
                rule_id=4, rule_content="全程双录", reason="r", confidence=0.9,
                timestamp_ms=500000, end_ms=500000, source="vision",
            ),
        ]
        visual_events = [{"event_type": "face_missing", "start_ms": 60000, "end_ms": 180000, "frame_path": "f.jpg"}]
        result = EvidenceEnricher().apply(vs, None, visual_events)
        assert result[0].evidence_url == "f.jpg"

    def test_transcript_sourced_violation_ignores_visual_events(self):
        vs = [Violation(rule_id=1, rule_content="r", reason="r", confidence=0.9, timestamp_ms=65000)]
        visual_events = [{"event_type": "face_missing", "start_ms": 60000, "end_ms": 180000, "frame_path": "f.jpg"}]
        result = EvidenceEnricher().apply(vs, None, visual_events)
        assert result[0].evidence_text is None


# ------------------------------------------------------------------ #
#  9. 完整性标记：截断 / 分块失败
# ------------------------------------------------------------------ #


def _entry(i: int, text: str) -> dict:
    return {
        "timestamp": f"00:{i:02d}",
        "timestamp_ms": i * 1000,
        "end_ms": i * 1000 + 900,
        "speaker": "讲师",
        "text_corrected": text,
    }


class TestReportCompleteness:
    @pytest.mark.asyncio
    async def test_truncated_flag_and_segment_counts(self, mock_client: MagicMock):
        settings = Settings(
            llm_base_url="http://localhost:11434",
            compliance_max_text_chars=25,
            compliance_group_by_source=False,
        )
        service = ComplianceService(mock_client, settings)
        mock_client.chat = AsyncMock(
            return_value=ChatResponse(content="[]", model="m")
        )
        entries = [_entry(i, "一二三四五六七八九十") for i in range(5)]  # 每条 10 字

        report = await service.audit([ComplianceRule(id=1, content="r")], entries)

        assert report.truncated is True
        assert report.total_segments == 5
        assert report.total_segments_checked == 2

    @pytest.mark.asyncio
    async def test_not_truncated_by_default(
        self, service: ComplianceService, mock_client: MagicMock
    ):
        mock_client.chat = AsyncMock(
            return_value=ChatResponse(content="[]", model="m")
        )
        report = await service.audit(
            [ComplianceRule(id=1, content="r")], [_entry(1, "内容")]
        )
        assert report.truncated is False
        assert report.failed_chunks == 0
        assert report.total_segments == report.total_segments_checked == 1

    @pytest.mark.asyncio
    async def test_all_chunks_failed_raises(
        self, service: ComplianceService, mock_client: MagicMock
    ):
        from copernicus.exceptions import ComplianceError

        mock_client.chat = AsyncMock(side_effect=RuntimeError("llm down"))
        with pytest.raises(ComplianceError):
            await service.audit(
                [ComplianceRule(id=1, content="r")], [_entry(1, "内容")]
            )

    @pytest.mark.asyncio
    async def test_partial_chunk_failure_is_reported(self, mock_client: MagicMock):
        settings = Settings(
            llm_base_url="http://localhost:11434",
            compliance_chunk_size=10,
            compliance_group_by_source=False,
        )
        service = ComplianceService(mock_client, settings)

        # 两个 chunk：第一个 chunk 的调用失败（LLMClient 已重试过，这里不再叠加重试），第二个成功
        mock_client.chat = AsyncMock(
            side_effect=[
                RuntimeError("boom"),
                ChatResponse(content="[]", model="m"),
            ]
        )
        entries = [_entry(1, "一二三四五六七八九十"), _entry(2, "甲乙丙丁戊己庚辛壬癸")]

        report = await service.audit([ComplianceRule(id=1, content="r")], entries)

        assert report.total_chunks == 2
        assert report.failed_chunks == 1


class TestChunkRetrySemantics:
    @pytest.mark.asyncio
    async def test_unparseable_output_is_reprompted_once(self, mock_client: MagicMock):
        service = ComplianceService(mock_client, Settings(llm_base_url="http://localhost:11434"))
        mock_client.chat = AsyncMock(
            side_effect=[
                ChatResponse(content="这不是 JSON", model="m"),
                ChatResponse(content="[]", model="m"),
            ]
        )

        report = await service.audit([ComplianceRule(id=1, content="r")], [_entry(1, "内容")])

        assert mock_client.chat.await_count == 2
        assert report.failed_chunks == 0

    @pytest.mark.asyncio
    async def test_transport_failure_is_not_retried_again_at_this_layer(self, mock_client: MagicMock):
        service = ComplianceService(mock_client, Settings(llm_base_url="http://localhost:11434"))
        mock_client.chat = AsyncMock(side_effect=RuntimeError("connection refused"))

        with pytest.raises(ComplianceError):  # 只有一个分块且失败：整体失败
            await service.audit([ComplianceRule(id=1, content="r")], [_entry(1, "内容")])

        assert mock_client.chat.await_count == 1


class TestSkippedRulesAreReported:
    @pytest.mark.asyncio
    async def test_ocr_only_rules_are_listed_when_there_is_no_ocr_data(self, mock_client: MagicMock):
        from copernicus.services.rule_registry import StructuredRule

        service = ComplianceService(mock_client, Settings(llm_base_url="http://localhost:11434"))
        service._registry.enrich = lambda rules: [
            StructuredRule(id=1, title="话术", content="a", category="forbidden_phrase", check_mode="semantic", evidence_sources=["transcript"]),
            StructuredRule(id=3, title="屏幕文字", content="b", category="visual_check", check_mode="visual", evidence_sources=["ocr"]),
        ]
        mock_client.chat = AsyncMock(return_value=ChatResponse(content="[]", model="m"))

        report = await service.audit([ComplianceRule(id=1, content="a")], [_entry(1, "内容")])
        assert report.skipped_rule_ids == [3]

        with_ocr = await service.audit(
            [ComplianceRule(id=1, content="a")],
            [_entry(1, "内容")],
            ocr_results=[{"timestamp_ms": 0, "text": "屏幕", "confidence": 0.9, "frame_path": "f.jpg"}],
        )
        assert with_ocr.skipped_rule_ids == []
