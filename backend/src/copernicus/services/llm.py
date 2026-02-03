"""Ollama native API client using httpx.

Provides async chat completion with support for num_ctx, temperature,
and JSON format — features not available via Ollama's OpenAI-compatible endpoint.
"""

import logging
from dataclasses import dataclass

import httpx

from copernicus.config import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str


@dataclass(frozen=True)
class ChatResponse:
    content: str
    model: str
    total_duration: int | None = None
    eval_count: int | None = None


class OllamaClient:
    """Async client for Ollama's native /api/chat endpoint."""

    def __init__(self, settings: Settings) -> None:
        base_url = settings.llm_base_url.rstrip("/")
        # If configured with OpenAI-compat path, strip /v1 to get Ollama root
        if base_url.endswith("/v1"):
            base_url = base_url[:-3]

        self._base_url = base_url
        self._model = settings.llm_model_name
        self._temperature = settings.llm_temperature
        self._num_ctx = settings.ollama_num_ctx
        self._timeout = settings.llm_timeout
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(settings.llm_timeout))

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        json_format: bool = False,
        num_ctx: int | None = None,
    ) -> ChatResponse:
        """Send a chat completion request to Ollama native API."""
        payload: dict = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            "options": {
                "num_ctx": num_ctx if num_ctx is not None else self._num_ctx,
                "temperature": temperature if temperature is not None else self._temperature,
            },
        }
        if json_format:
            payload["format"] = "json"

        response = await self._client.post(
            f"{self._base_url}/api/chat",
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

        content = data.get("message", {}).get("content", "")
        logger.debug("Ollama raw response (first 200 chars): %s", content[:200])

        return ChatResponse(
            content=content,
            model=data.get("model", self._model),
            total_duration=data.get("total_duration"),
            eval_count=data.get("eval_count"),
        )

    async def is_reachable(self) -> bool:
        """Check if the Ollama server is reachable."""
        try:
            response = await self._client.get(
                f"{self._base_url}/api/tags",
                timeout=httpx.Timeout(5.0),
            )
            return response.status_code == 200
        except Exception:
            return False

    async def close(self) -> None:
        await self._client.aclose()
