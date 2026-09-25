"""CorrectorService.correct_transcript：四阶段纠正的编排与降级行为。"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from copernicus.config import Settings
from copernicus.services.corrector import CorrectorService
from copernicus.services.llm import ChatResponse


def _llm_reply(entries: list[dict]) -> ChatResponse:
    return ChatResponse(content=json.dumps({"entries": entries}, ensure_ascii=False), model="m")


@pytest.fixture
def corrector(mock_client: MagicMock) -> CorrectorService:
    return CorrectorService(mock_client, Settings(llm_base_url="http://localhost:11434"))


class TestCorrectTranscript:
    async def test_empty_input_needs_no_llm_call(self, corrector, mock_client):
        mock_client.chat = AsyncMock()
        assert await corrector.correct_transcript([]) == {}
        mock_client.chat.assert_not_awaited()

    async def test_noise_only_entries_are_blanked_without_calling_the_llm(self, corrector, mock_client):
        mock_client.chat = AsyncMock()
        result = await corrector.correct_transcript([{"id": 1, "text": "嗯"}, {"id": 2, "text": "啊。"}])
        assert result == {1: "", 2: ""}
        mock_client.chat.assert_not_awaited()

    async def test_llm_output_replaces_text_and_noise_ids_are_still_reported(self, corrector, mock_client):
        mock_client.chat = AsyncMock(return_value=_llm_reply([{"id": 2, "text": "今天开会。"}]))
        result = await corrector.correct_transcript(
            [{"id": 1, "text": "嗯"}, {"id": 2, "text": "今天开会那个那个"}]
        )
        assert result == {1: "", 2: "今天开会。"}

    async def test_llm_failure_falls_back_to_the_preprocessed_text(self, corrector, mock_client):
        mock_client.chat = AsyncMock(side_effect=RuntimeError("LLM 不可用"))
        result = await corrector.correct_transcript([{"id": 1, "text": "这个这个方案不错"}])
        assert result == {1: "这个方案不错"}  # 规则预处理的结果保留，只是没有 LLM 润色

    async def test_entries_missing_from_the_llm_reply_keep_their_text(self, corrector, mock_client):
        mock_client.chat = AsyncMock(return_value=_llm_reply([{"id": 1, "text": "第一句。"}]))
        result = await corrector.correct_transcript([{"id": 1, "text": "第一句"}, {"id": 2, "text": "第二句"}])
        assert result == {1: "第一句。", 2: "第二句"}

    async def test_truncated_json_is_salvaged_by_regex(self, corrector, mock_client):
        broken = '{"entries": [{"id": 1, "text": "修好了。"}, {"id": 2, "te'
        mock_client.chat = AsyncMock(return_value=ChatResponse(content=broken, model="m"))
        result = await corrector.correct_transcript([{"id": 1, "text": "修好了"}, {"id": 2, "text": "原文二"}])
        assert result == {1: "修好了。", 2: "原文二"}

    async def test_progress_reports_each_batch(self, corrector, mock_client):
        mock_client.chat = AsyncMock(side_effect=lambda **kw: _llm_reply([]))
        progress: list[tuple[int, int]] = []
        entries = [{"id": i, "text": "内容" * 5} for i in range(40)]  # 超过单批 15 条 → 多个批次

        await corrector.correct_transcript(entries, batch_size=15, on_progress=lambda c, t: progress.append((c, t)))

        total = progress[-1][1]
        assert total >= 3 and [c for c, _ in progress] == list(range(1, total + 1))

    async def test_cpu_stages_run_off_the_event_loop(self, mock_client):
        """MacBERT 首次加载可能耗时数十秒：不能在事件循环线程里同步执行。"""
        import threading

        seen: dict[str, int] = {}
        loop_thread = threading.get_ident()

        class SlowCorrector:
            def correct_entries(self, entries):
                seen["thread"] = threading.get_ident()
                return entries

        service = CorrectorService(
            mock_client, Settings(llm_base_url="http://localhost:11434"), text_corrector=SlowCorrector()
        )
        mock_client.chat = AsyncMock(return_value=_llm_reply([]))

        await service.correct_transcript([{"id": 1, "text": "测试内容"}])

        assert seen["thread"] != loop_thread

    async def test_batches_run_concurrently_up_to_the_configured_limit(self, mock_client):
        settings = Settings(llm_base_url="http://localhost:11434", correction_max_concurrency=2)
        service = CorrectorService(mock_client, settings)
        running = peak = 0

        async def chat(**kwargs):
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.01)
            running -= 1
            return _llm_reply([])

        mock_client.chat = chat
        await service.correct_transcript([{"id": i, "text": "内容" * 5} for i in range(60)], batch_size=15)

        assert peak == 2


class TestBatching:
    def test_respects_both_entry_and_char_limits(self):
        entries = [{"id": i, "text": "x" * 300} for i in range(5)]
        batches = CorrectorService._create_transcript_batches(entries, max_entries=15, max_chars=800)
        assert [len(b) for b in batches] == [2, 2, 1]

    def test_oversized_entry_gets_its_own_batch(self):
        entries = [{"id": 1, "text": "a"}, {"id": 2, "text": "b" * 900}, {"id": 3, "text": "c"}]
        batches = CorrectorService._create_transcript_batches(entries, max_entries=15, max_chars=800)
        assert [[e["id"] for e in b] for b in batches] == [[1], [2], [3]]
