from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from copernicus.config import Settings
from copernicus.services.corrector import CorrectorService


@pytest.fixture
def mock_settings() -> Settings:
    return Settings(
        llm_api_key="test-key",
        llm_base_url="https://api.example.com",
        llm_model_name="test-model",
        llm_temperature=0.1,
        correction_chunk_size=800,
        correction_overlap=100,
        correction_max_concurrency=3,
    )


@pytest.fixture
def corrector(mock_settings: Settings) -> CorrectorService:
    with patch("copernicus.services.corrector.AsyncOpenAI"):
        return CorrectorService(mock_settings)


class TestCorrect:
    @pytest.mark.asyncio
    async def test_empty_text_returns_as_is(self, corrector: CorrectorService):
        result = await corrector.correct("   ")
        assert result == "   "

    @pytest.mark.asyncio
    async def test_calls_llm_and_returns_corrected(self, corrector: CorrectorService):
        mock_choice = MagicMock()
        mock_choice.message.content = "纠正后的文本"
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        corrector._client.chat.completions.create = AsyncMock(return_value=mock_response)

        result = await corrector.correct("原始文本")
        assert result == "纠正后的文本"

    @pytest.mark.asyncio
    async def test_fallback_on_llm_failure(self, corrector: CorrectorService):
        corrector._client.chat.completions.create = AsyncMock(
            side_effect=Exception("API error")
        )

        result = await corrector.correct("原始文本")
        # Should fall back to raw text
        assert result == "原始文本"

    @pytest.mark.asyncio
    async def test_concurrent_chunks(self, corrector: CorrectorService):
        """Verify multiple chunks are processed concurrently."""
        mock_choice = MagicMock()
        mock_choice.message.content = "corrected"
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        corrector._client.chat.completions.create = AsyncMock(return_value=mock_response)
        corrector._chunk_size = 10
        corrector._overlap = 2

        text = "这是一段需要分块处理的较长文本，用来测试并发处理是否正常工作。"
        await corrector.correct(text)

        assert corrector._client.chat.completions.create.call_count > 1


class TestCorrectSegments:
    @pytest.mark.asyncio
    async def test_empty_list(self, corrector: CorrectorService):
        result = await corrector.correct_segments([])
        assert result == []

    @pytest.mark.asyncio
    async def test_corrects_each_segment(self, corrector: CorrectorService):
        mock_choice = MagicMock()
        mock_choice.message.content = "纠正文本"
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        corrector._client.chat.completions.create = AsyncMock(return_value=mock_response)

        result = await corrector.correct_segments(["段落一", "段落二"])
        assert result == ["纠正文本", "纠正文本"]
        assert corrector._client.chat.completions.create.call_count == 2


class TestIsReachable:
    @pytest.mark.asyncio
    async def test_reachable(self, corrector: CorrectorService):
        corrector._client.models.list = AsyncMock(return_value=[])
        assert await corrector.is_reachable() is True

    @pytest.mark.asyncio
    async def test_unreachable(self, corrector: CorrectorService):
        corrector._client.models.list = AsyncMock(side_effect=Exception("timeout"))
        assert await corrector.is_reachable() is False
