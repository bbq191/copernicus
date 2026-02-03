import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from copernicus.config import Settings
from copernicus.services.evaluator import EvaluatorService
from copernicus.services.llm import ChatResponse


@pytest.fixture
def mock_settings() -> Settings:
    return Settings(
        llm_api_key="test-key",
        llm_base_url="http://localhost:11434",
        llm_model_name="test-model",
        llm_temperature=0.1,
    )


@pytest.fixture
def mock_client() -> MagicMock:
    return MagicMock()


@pytest.fixture
def evaluator(mock_client: MagicMock, mock_settings: Settings) -> EvaluatorService:
    return EvaluatorService(mock_client, mock_settings)


SAMPLE_EVALUATION_JSON = {
    "meta": {
        "title": "2025全球经济格局分析",
        "category": "宏观经济",
        "keywords": ["全球经济", "关税", "贸易战"],
    },
    "scores": {
        "logic": 32,
        "info_density": 30,
        "expression": 25,
        "total": 87,
    },
    "analysis": {
        "main_points": ["全球经济增速放缓", "贸易摩擦加剧"],
        "key_data": ["GDP增速2.8%", "关税上调25%"],
        "sentiment": "中立",
    },
    "summary": "本视频分析了2025年全球经济格局。",
}


class TestEvaluate:
    @pytest.mark.asyncio
    async def test_evaluate_returns_structured_result(self, evaluator: EvaluatorService, mock_client: MagicMock):
        mock_client.chat = AsyncMock(
            return_value=ChatResponse(
                content=json.dumps(SAMPLE_EVALUATION_JSON, ensure_ascii=False),
                model="test-model",
            )
        )

        result = await evaluator.evaluate("测试文本")
        assert result.meta.title == "2025全球经济格局分析"
        assert result.scores.total == 87
        assert result.analysis.sentiment == "中立"

    @pytest.mark.asyncio
    async def test_evaluate_strips_markdown_fences(self, evaluator: EvaluatorService, mock_client: MagicMock):
        wrapped = f"```json\n{json.dumps(SAMPLE_EVALUATION_JSON, ensure_ascii=False)}\n```"
        mock_client.chat = AsyncMock(
            return_value=ChatResponse(content=wrapped, model="test-model")
        )

        result = await evaluator.evaluate("测试文本")
        assert result.scores.total == 87

    @pytest.mark.asyncio
    async def test_evaluate_raises_on_invalid_json(self, evaluator: EvaluatorService, mock_client: MagicMock):
        mock_client.chat = AsyncMock(
            return_value=ChatResponse(content="这不是JSON", model="test-model")
        )

        with pytest.raises(json.JSONDecodeError):
            await evaluator.evaluate("测试文本")

    @pytest.mark.asyncio
    async def test_evaluate_uses_defaults_for_missing_fields(self, evaluator: EvaluatorService, mock_client: MagicMock):
        minimal_json = {"meta": {"title": "测试"}, "summary": "摘要"}
        mock_client.chat = AsyncMock(
            return_value=ChatResponse(
                content=json.dumps(minimal_json, ensure_ascii=False),
                model="test-model",
            )
        )

        result = await evaluator.evaluate("测试文本")
        assert result.meta.title == "测试"
        assert result.scores.total == 0
        assert result.analysis.main_points == []
