import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from copernicus.config import Settings
from copernicus.services.evaluator import EvaluatorService
from copernicus.services.llm import ChatResponse

_TEMPLATE_PROMPT = "你是一个会议助手，请生成夕会纪要。"

SAMPLE_EVALUATION_JSON = {
    "formatted_content": "## 今日总结\n- 张三完成了前端开发\n\n## 明日计划\n- 与前端联调模板",
    "title": "前端开发进度复盘夕会",
}


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


class TestEvaluate:
    @pytest.mark.asyncio
    async def test_evaluate_returns_structured_result(
        self, evaluator: EvaluatorService, mock_client: MagicMock
    ):
        mock_client.chat = AsyncMock(
            return_value=ChatResponse(
                content=json.dumps(SAMPLE_EVALUATION_JSON, ensure_ascii=False),
                model="test-model",
            )
        )

        result = await evaluator.evaluate("测试文本", _TEMPLATE_PROMPT)
        assert result.title == "前端开发进度复盘夕会"
        assert "今日总结" in result.formatted_content

    @pytest.mark.asyncio
    async def test_evaluate_strips_markdown_fences(
        self, evaluator: EvaluatorService, mock_client: MagicMock
    ):
        wrapped = f"```json\n{json.dumps(SAMPLE_EVALUATION_JSON, ensure_ascii=False)}\n```"
        mock_client.chat = AsyncMock(
            return_value=ChatResponse(content=wrapped, model="test-model")
        )

        result = await evaluator.evaluate("测试文本", _TEMPLATE_PROMPT)
        assert result.title == "前端开发进度复盘夕会"

    @pytest.mark.asyncio
    async def test_evaluate_raises_on_invalid_json(
        self, evaluator: EvaluatorService, mock_client: MagicMock
    ):
        mock_client.chat = AsyncMock(
            return_value=ChatResponse(content="这不是JSON", model="test-model")
        )

        with pytest.raises(Exception):
            await evaluator.evaluate("测试文本", _TEMPLATE_PROMPT)

    @pytest.mark.asyncio
    async def test_evaluate_uses_defaults_for_missing_fields(
        self, evaluator: EvaluatorService, mock_client: MagicMock
    ):
        minimal_json = {"formatted_content": "会议纪要内容"}
        mock_client.chat = AsyncMock(
            return_value=ChatResponse(
                content=json.dumps(minimal_json, ensure_ascii=False),
                model="test-model",
            )
        )

        result = await evaluator.evaluate("测试文本", _TEMPLATE_PROMPT)
        assert result.formatted_content == "会议纪要内容"
        assert result.title == ""
