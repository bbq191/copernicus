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


class TestCompleteness:
    @pytest.mark.asyncio
    async def test_truncated_flag_set_when_text_exceeds_limit(
        self, mock_client: MagicMock
    ):
        settings = Settings(
            llm_base_url="http://localhost:11434",
            evaluation_max_text_chars=10,
            evaluation_chunk_size=100,
        )
        service = EvaluatorService(mock_client, settings)
        mock_client.chat = AsyncMock(
            return_value=ChatResponse(
                content=json.dumps(SAMPLE_EVALUATION_JSON, ensure_ascii=False),
                model="test-model",
            )
        )

        result = await service.evaluate("字" * 50, _TEMPLATE_PROMPT)

        assert result.truncated is True
        assert result.degraded_chunks == 0

    @pytest.mark.asyncio
    async def test_llm_cannot_forge_completeness_fields(
        self, evaluator: EvaluatorService, mock_client: MagicMock
    ):
        forged = {**SAMPLE_EVALUATION_JSON, "truncated": True, "degraded_chunks": 9}
        mock_client.chat = AsyncMock(
            return_value=ChatResponse(
                content=json.dumps(forged, ensure_ascii=False), model="test-model"
            )
        )

        result = await evaluator.evaluate("短文本", _TEMPLATE_PROMPT)

        assert result.truncated is False
        assert result.degraded_chunks == 0

    @pytest.mark.asyncio
    async def test_map_failure_counted_as_degraded(self, mock_client: MagicMock):
        settings = Settings(
            llm_base_url="http://localhost:11434",
            evaluation_chunk_size=20,
        )
        service = EvaluatorService(mock_client, settings)
        reduce_response = ChatResponse(
            content=json.dumps(SAMPLE_EVALUATION_JSON, ensure_ascii=False),
            model="test-model",
        )

        async def fake_chat(*, messages, **kwargs):
            # Map 调用不带 json_format；让所有 Map 失败，Reduce 成功
            if kwargs.get("json_format"):
                return reduce_response
            raise RuntimeError("map failed")

        mock_client.chat = AsyncMock(side_effect=fake_chat)

        result = await service.evaluate("字" * 60, _TEMPLATE_PROMPT)

        assert result.degraded_chunks >= 2
