"""OpenAI 兼容协议客户端（DeepSeek / vLLM / 通义 / OpenAI 等）。

请求地址为 ``{LLM_BASE_URL}/chat/completions``，需要 /v1 的服务请在 base_url 中带上，
例如 ``https://api.openai.com/v1``；DeepSeek 直接使用 ``https://api.deepseek.com``。
Ollama 专有参数（num_ctx、think、keep_alive）在该协议下被忽略。
"""

import json
import logging

from copernicus.config import Settings
from copernicus.services.llm.base import ChatResponse, LLMClient

logger = logging.getLogger(__name__)

_SSE_DATA_PREFIX = "data:"
_SSE_DONE = "[DONE]"


class OpenAICompatClient(LLMClient):
    """OpenAI 兼容 /chat/completions 端点的异步流式客户端。"""

    @classmethod
    def from_settings(cls, settings: Settings) -> "OpenAICompatClient":
        headers = (
            {"Authorization": f"Bearer {settings.llm_api_key}"}
            if settings.llm_api_key
            else None
        )
        return cls(
            base_url=settings.llm_base_url,
            model=settings.llm_model_name,
            temperature=settings.llm_temperature,
            timeout=settings.llm_timeout,
            max_retries=settings.llm_max_retries,
            retry_delay=settings.llm_retry_delay,
            max_concurrent=settings.llm_max_concurrent,
            headers=headers,
        )

    async def _do_chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None,
        json_format: bool,
        num_ctx: int | None,
        think: bool | None,
        num_predict: int | None,
        timeout: float | None,
    ) -> ChatResponse:
        payload: dict = {
            "model": self._model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
            "temperature": temperature if temperature is not None else self._temperature,
        }
        if num_predict is not None:
            payload["max_tokens"] = num_predict
        if json_format:
            payload["response_format"] = {"type": "json_object"}

        content_parts: list[str] = []
        model_name = self._model
        completion_tokens: int | None = None

        async with self._client.stream(
            "POST",
            f"{self._base_url}/chat/completions",
            json=payload,
            timeout=self._request_timeout(timeout),
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                line = line.strip()
                if not line.startswith(_SSE_DATA_PREFIX):
                    continue
                data = line[len(_SSE_DATA_PREFIX):].strip()
                if data == _SSE_DONE:
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    logger.warning("Failed to parse SSE chunk: %s", data[:100])
                    continue
                model_name = chunk.get("model", model_name)
                for choice in chunk.get("choices") or []:
                    piece = (choice.get("delta") or {}).get("content")
                    if piece:
                        content_parts.append(piece)
                usage = chunk.get("usage")
                if usage:
                    completion_tokens = usage.get("completion_tokens")

        content = "".join(content_parts)
        logger.debug("OpenAI-compat response (first 200 chars): %s", content[:200])
        return ChatResponse(
            content=content, model=model_name, eval_count=completion_tokens
        )

    async def is_reachable(self) -> bool:
        try:
            response = await self._client.get(f"{self._base_url}/models", timeout=5.0)
            return response.status_code == 200
        except Exception as e:
            logger.debug("LLM endpoint unreachable: %s", e)
            return False
