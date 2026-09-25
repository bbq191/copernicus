"""Ollama 原生 API 客户端（基于 httpx）。

使用原生 /api/chat 而非 OpenAI 兼容端点，因为后者不支持 num_ctx 与 keep_alive。

关键设计：使用流式响应 (stream=True) 避免长推理超时
- 非流式模式下，httpx 必须等待 Ollama 完成整个推理才能收到响应
- 流式模式下，只要连接保持活跃（每 chunk 间隔 < timeout），就不会超时
"""

import json
import logging

from copernicus.config import Settings
from copernicus.services.llm.base import ChatResponse, LLMClient

logger = logging.getLogger(__name__)


def normalize_ollama_base_url(base_url: str) -> str:
    """去掉误配的 /v1 后缀，得到 Ollama 根地址。"""
    base_url = base_url.rstrip("/")
    return base_url[:-3] if base_url.endswith("/v1") else base_url


class OllamaClient(LLMClient):
    """Ollama 原生 /api/chat 端点的异步客户端。"""

    def __init__(self, *, num_ctx: int, keep_alive: int, **base_kwargs) -> None:
        super().__init__(**base_kwargs)
        self._num_ctx = num_ctx
        self._keep_alive = keep_alive

    @classmethod
    def from_settings(cls, settings: Settings) -> "OllamaClient":
        return cls(
            base_url=normalize_ollama_base_url(settings.llm_base_url),
            model=settings.llm_model_name,
            temperature=settings.llm_temperature,
            timeout=settings.llm_timeout,
            max_retries=settings.llm_max_retries,
            retry_delay=settings.llm_retry_delay,
            max_concurrent=settings.llm_max_concurrent,
            num_ctx=settings.ollama_num_ctx,
            keep_alive=settings.ollama_keep_alive,
        )

    @classmethod
    def for_rewrite(cls, settings: Settings) -> "OllamaClient":
        """TTS 改写专用客户端，固定指向本地 Ollama，与主 LLM 配置解耦。"""
        return cls(
            base_url=settings.tts_rewrite_base_url,
            model=settings.tts_rewrite_model,
            temperature=0.75,
            timeout=60.0,
            max_retries=1,
            retry_delay=1.0,
            max_concurrent=settings.llm_max_concurrent,
            connect_timeout=10.0,
            num_ctx=settings.tts_rewrite_num_ctx,
            keep_alive=0,
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
        options: dict = {
            "num_ctx": num_ctx if num_ctx is not None else self._num_ctx,
            "temperature": temperature if temperature is not None else self._temperature,
        }
        if num_predict is not None:
            options["num_predict"] = num_predict

        payload: dict = {
            "model": self._model,
            "messages": messages,
            "stream": True,
            "options": options,
            "keep_alive": self._keep_alive,
        }
        # 仅当显式指定时才设置 think 参数（qwen3 thinking 模式开关）
        if think is not None:
            payload["think"] = think
        if json_format:
            payload["format"] = "json"

        content_parts: list[str] = []
        model_name = self._model
        total_duration: int | None = None
        eval_count: int | None = None

        async with self._client.stream(
            "POST",
            f"{self._base_url}/api/chat",
            json=payload,
            timeout=self._request_timeout(timeout),
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning("Failed to parse streaming chunk: %s", line[:100])
                    continue
                if "message" in chunk and "content" in chunk["message"]:
                    content_parts.append(chunk["message"]["content"])
                # 最后一个 chunk 包含统计信息
                if chunk.get("done", False):
                    model_name = chunk.get("model", self._model)
                    total_duration = chunk.get("total_duration")
                    eval_count = chunk.get("eval_count")

        content = "".join(content_parts)
        logger.debug("Ollama streaming response (first 200 chars): %s", content[:200])
        return ChatResponse(
            content=content,
            model=model_name,
            total_duration=total_duration,
            eval_count=eval_count,
        )

    async def is_reachable(self) -> bool:
        try:
            response = await self._client.get(f"{self._base_url}/api/tags", timeout=5.0)
            return response.status_code == 200
        except Exception as e:
            logger.debug("Ollama unreachable: %s", e)
            return False
