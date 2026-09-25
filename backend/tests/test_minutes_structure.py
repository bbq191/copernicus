"""纪要结构化提取：引文定位时间点、容错解析、分块与降级。"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from copernicus.config import Settings
from copernicus.schemas.evaluation import EvaluationResult
from copernicus.schemas.transcription import TranscriptEntrySchema, TranscriptResponse
from copernicus.services.minutes_structure import (
    MinutesStructurer,
    _chunk_entries,
    _parse_chunk,
    locate_quote,
)
from copernicus.services.task_executor import TaskExecutor
from copernicus.services.task_state import TaskInfo


def _entry(ms: int, text: str, speaker: str = "说话人1") -> TranscriptEntrySchema:
    return TranscriptEntrySchema(
        timestamp="00:00", timestamp_ms=ms, end_ms=ms + 1000, speaker=speaker, text=text, text_corrected=text,
    )


ENTRIES = [
    _entry(1000, "大家好，今天讨论第三季度的上线计划。"),
    _entry(9000, "小王负责在下周五之前完成压力测试。"),
    _entry(20000, "那我们就定在十月一号正式发布，没有问题吧。"),
]


class TestLocateQuote:
    def test_exact_substring_ignores_punctuation_and_spacing(self):
        assert locate_quote("小王负责在下周五之前完成压力测试", ENTRIES) == 9000
        assert locate_quote("定在 十月一号，正式发布", ENTRIES) == 20000

    def test_quote_spanning_two_adjacent_sentences(self):
        assert locate_quote("上线计划小王负责在下周五", ENTRIES) == 1000

    def test_fuzzy_match_tolerates_a_slightly_reworded_quote(self):
        assert locate_quote("小王负责下周五前完成压力测试工作", ENTRIES) == 9000

    def test_hallucinated_or_too_short_quotes_are_not_located(self):
        assert locate_quote("我们需要采购三十台服务器", ENTRIES) is None
        assert locate_quote("好的", ENTRIES) is None
        assert locate_quote("", ENTRIES) is None

    def test_empty_transcript(self):
        assert locate_quote("小王负责在下周五之前完成压力测试", []) is None


class TestParseChunk:
    def test_items_are_built_with_timestamps_from_their_quotes(self):
        data = {
            "action_items": [{"task": "完成压力测试", "owner": "小王", "due": "下周五", "quote": "小王负责在下周五之前完成压力测试"}],
            "decisions": [{"content": "十月一号发布", "quote": "定在十月一号正式发布"}],
        }
        minutes = _parse_chunk(data, ENTRIES)
        assert (minutes.action_items[0].owner, minutes.action_items[0].timestamp_ms) == ("小王", 9000)
        assert minutes.decisions[0].timestamp_ms == 20000

    def test_malformed_entries_are_dropped_without_losing_the_rest(self):
        data = {
            "action_items": ["oops", {"owner": "x"}, {"task": "  "}, {"task": "有效事项", "owner": None, "quote": 5}],
            "decisions": None,
        }
        minutes = _parse_chunk(data, ENTRIES)
        assert [a.task for a in minutes.action_items] == ["有效事项"]
        assert minutes.action_items[0].owner == "" and minutes.action_items[0].timestamp_ms is None

    def test_non_object_output_is_an_error(self):
        with pytest.raises(ValueError):
            _parse_chunk(["not", "an", "object"], ENTRIES)


class TestChunking:
    def test_groups_by_character_budget_and_respects_the_total_cap(self):
        entries = [_entry(i * 1000, "字" * 92) for i in range(10)]  # 每条 100（含行首开销）
        assert [len(c) for c in _chunk_entries(entries, chunk_chars=300, max_chars=10_000)] == [3, 3, 3, 1]
        assert sum(len(c) for c in _chunk_entries(entries, chunk_chars=300, max_chars=450)) == 4


def _structurer(*replies, **settings) -> tuple[MinutesStructurer, MagicMock]:
    client = MagicMock()
    outcomes = list(replies)

    async def chat(**_kwargs):
        reply = outcomes.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return MagicMock(content=reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False))

    client.chat = chat
    return MinutesStructurer(client, Settings(**settings)), client


ONE_ITEM = {"action_items": [{"task": "完成压力测试", "quote": "完成压力测试"}], "decisions": []}


class TestExtract:
    async def test_single_chunk_end_to_end(self):
        structurer, _ = _structurer(ONE_ITEM)
        minutes = await structurer.extract(ENTRIES)
        assert minutes.status == "ok" and minutes.action_items[0].timestamp_ms == 9000

    async def test_duplicates_across_chunks_are_merged(self):
        structurer, _ = _structurer(ONE_ITEM, ONE_ITEM, evaluation_chunk_size=60)
        minutes = await structurer.extract(ENTRIES)
        assert len(minutes.action_items) == 1

    async def test_partial_failure_keeps_the_good_chunks(self):
        structurer, _ = _structurer(ONE_ITEM, RuntimeError("boom"), evaluation_chunk_size=60)
        minutes = await structurer.extract(ENTRIES)
        assert minutes.status == "partial" and len(minutes.action_items) == 1

    async def test_all_chunks_failing_raises(self):
        structurer, _ = _structurer("not json at all")
        with pytest.raises(json.JSONDecodeError):
            await structurer.extract(ENTRIES)

    async def test_no_entries_is_an_empty_ok_result(self):
        structurer, _ = _structurer()
        assert (await structurer.extract([])).action_items == []


def _executor(structurer) -> tuple[TaskExecutor, MagicMock]:
    persistence = MagicMock()
    persistence.load_json.return_value = None
    evaluator = MagicMock()
    evaluator.evaluate = AsyncMock(return_value=EvaluationResult(title="纪要", formatted_content="内容"))
    executor = TaskExecutor(MagicMock(), persistence, Settings(), evaluator=evaluator, structurer=structurer)
    return executor, persistence


def _transcript() -> TranscriptResponse:
    return TranscriptResponse(transcript=ENTRIES, processing_time_ms=1)


class TestExecutorIntegration:
    async def test_summary_carries_structure_and_status(self):
        structurer, _ = _structurer(ONE_ITEM)
        executor, persistence = _executor(structurer)
        task = TaskInfo("t" * 32)

        await executor._generate_summary(task, _transcript(), "universal")

        saved = persistence.save_json.call_args.args[2]
        assert saved.structure_status == "ok" and saved.action_items[0].timestamp_ms == 9000
        assert saved.formatted_content == "内容"

    async def test_structure_failure_degrades_but_keeps_the_summary(self):
        structurer, _ = _structurer(RuntimeError("LLM down"))
        executor, persistence = _executor(structurer)

        await executor._generate_summary(TaskInfo("t" * 32), _transcript(), "universal")

        saved = persistence.save_json.call_args.args[2]
        assert saved.structure_status == "failed" and saved.action_items == [] and saved.title == "纪要"

    async def test_disabled_structuring_leaves_it_skipped_and_makes_no_extra_call(self):
        structurer, _ = _structurer(minutes_structure_enabled=False)
        executor, persistence = _executor(structurer)

        await executor._generate_summary(TaskInfo("t" * 32), _transcript(), "universal")

        assert persistence.save_json.call_args.args[2].structure_status == "skipped"

    async def test_rerun_reads_entries_from_the_parent_transcript(self):
        structurer, _ = _structurer(ONE_ITEM)
        executor, persistence = _executor(structurer)
        persistence.load_json.return_value = _transcript().model_dump()
        task = TaskInfo("c" * 32, eval_only=True, parent_task_id="p" * 32)

        await executor.text_evaluation(task, "文本", "universal")

        assert task.result.evaluation.structure_status == "ok"
        assert task.result.evaluation.action_items[0].timestamp_ms == 9000

    async def test_rerun_without_a_parent_transcript_skips_structuring(self):
        structurer, _ = _structurer()
        executor, _ = _executor(structurer)
        task = TaskInfo("c" * 32, eval_only=True)
        await executor.text_evaluation(task, "文本", "universal")
        assert task.result.evaluation.structure_status == "skipped"


def test_legacy_evaluation_json_still_loads():
    result = EvaluationResult.model_validate({"formatted_content": "x", "title": "t"})
    assert result.structure_status == "skipped" and result.action_items == [] and result.decisions == []
