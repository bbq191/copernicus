"""Ollama native API client using httpx.

Provides async chat completion with support for num_ctx, temperature,
and JSON format — features not available via Ollama's OpenAI-compatible endpoint.

关键设计：使用流式响应 (stream=True) 避免长推理超时
- 非流式模式下，httpx 必须等待 Ollama 完成整个推理才能收到响应
- 对于复杂文本，推理时间可能超过 120 秒，导致 ReadTimeout
- 流式模式下，只要连接保持活跃（每 chunk 间隔 < timeout），就不会超时
"""

import asyncio
import json
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
        self._max_retries = settings.llm_max_retries
        self._retry_delay = settings.llm_retry_delay
        self._semaphore = asyncio.Semaphore(settings.llm_max_concurrent)
        # 使用较长的连接超时，但读取超时保持合理（流式模式下每个 chunk 间隔不会太长）
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=30.0,
                read=settings.llm_timeout,  # 每个 chunk 的读取超时
                write=30.0,
                pool=30.0,
            )
        )

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        json_format: bool = False,
        num_ctx: int | None = None,
        think: bool | None = None,
        num_predict: int | None = None,
        timeout: float | None = None,
    ) -> ChatResponse:
        """Send a streaming chat completion request to Ollama native API.

        使用流式响应避免长推理超时：Ollama 会逐 token 返回，
        只要 token 生成间隔 < read_timeout，连接就不会断开。

        内置重试机制：遇到网络错误或 HTTP 5xx 时自动重试，指数退避。

        Args:
            think: 是否启用 qwen3 thinking 模式。
                   None = 使用默认行为（不设置参数，由 Ollama 决定）
                   False = 禁用 thinking，减少 token 消耗（适合批量纠正任务）
                   True = 显式启用 thinking（适合需要深度推理的任务）
            num_predict: 最大输出 token 数，限制 thinking 长度避免无限推理
            timeout: 覆盖默认 read timeout（秒），用于大文本 prompt evaluation 耗时较长的场景
        """
        last_error: Exception | None = None
        max_attempts = 1 + self._max_retries

        for attempt in range(1, max_attempts + 1):
            try:
                async with self._semaphore:
                    return await self._do_chat(
                        messages,
                        temperature=temperature,
                        json_format=json_format,
                        num_ctx=num_ctx,
                        think=think,
                        num_predict=num_predict,
                        timeout=timeout,
                    )
            except (httpx.ReadTimeout, httpx.ConnectError, httpx.HTTPStatusError) as e:
                last_error = e
                if attempt >= max_attempts:
                    raise
                delay = self._retry_delay * (2 ** (attempt - 1))
                logger.warning(
                    "LLM attempt %d/%d failed, retry in %.1fs: %s",
                    attempt,
                    max_attempts,
                    delay,
                    e,
                )
                await asyncio.sleep(delay)

        raise last_error  # type: ignore[misc]

    async def _do_chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        json_format: bool = False,
        num_ctx: int | None = None,
        think: bool | None = None,
        num_predict: int | None = None,
        timeout: float | None = None,
    ) -> ChatResponse:
        """Execute a single streaming chat request (no retry logic)."""
        options: dict = {
            "num_ctx": num_ctx if num_ctx is not None else self._num_ctx,
            "temperature": temperature if temperature is not None else self._temperature,
        }
        if num_predict is not None:
            options["num_predict"] = num_predict

        payload: dict = {
            "model": self._model,
            "messages": messages,
            "stream": True,  # 关键：使用流式响应
            "options": options,
        }
        # 仅当显式指定时才设置 think 参数
        if think is not None:
            payload["think"] = think
        if json_format:
            payload["format"] = "json"

        content_parts: list[str] = []
        model_name = self._model
        total_duration: int | None = None
        eval_count: int | None = None

        # 大文本 prompt evaluation 可能超过默认 read timeout，允许调用方覆盖
        request_timeout = (
            httpx.Timeout(connect=30.0, read=timeout, write=30.0, pool=30.0)
            if timeout is not None
            else httpx.USE_CLIENT_DEFAULT
        )

        async with self._client.stream(
            "POST",
            f"{self._base_url}/api/chat",
            json=payload,
            timeout=request_timeout,
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                try:
                    chunk = json.loads(line)
                    # 累积内容
                    if "message" in chunk and "content" in chunk["message"]:
                        content_parts.append(chunk["message"]["content"])
                    # 最后一个 chunk 包含统计信息
                    if chunk.get("done", False):
                        model_name = chunk.get("model", self._model)
                        total_duration = chunk.get("total_duration")
                        eval_count = chunk.get("eval_count")
                except json.JSONDecodeError:
                    logger.warning("Failed to parse streaming chunk: %s", line[:100])

        content = "".join(content_parts)
        logger.debug("Ollama streaming response (first 200 chars): %s", content[:200])

        return ChatResponse(
            content=content,
            model=model_name,
            total_duration=total_duration,
            eval_count=eval_count,
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
