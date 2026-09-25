"""LLM 客户端抽象基类：统一并发限流与重试策略，协议细节由子类实现。"""

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

_RETRYABLE_TRANSPORT_ERRORS = (
    httpx.ReadTimeout,
    httpx.ConnectError,
    httpx.RemoteProtocolError,  # 流式响应被对端中断
    httpx.ReadError,
)


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


def _is_retryable(exc: Exception) -> bool:
    """网络错误、5xx、429 值得重试；其余 4xx（鉴权/参数错误）重试无意义。"""
    if isinstance(exc, _RETRYABLE_TRANSPORT_ERRORS):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return status >= 500 or status == 429
    return False


class LLMClient(ABC):
    """带全局并发信号量与指数退避重试的 LLM 客户端基类。"""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        temperature: float,
        timeout: float,
        max_retries: int,
        retry_delay: float,
        max_concurrent: int,
        connect_timeout: float = 30.0,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._temperature = temperature
        self._timeout = timeout
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self._semaphore = asyncio.Semaphore(max_concurrent)
        # 读取超时按"每个流式 chunk 的间隔"计算，只要连接保持活跃就不会超时
        self._client = httpx.AsyncClient(
            headers=headers,
            timeout=httpx.Timeout(
                connect=connect_timeout, read=timeout, write=30.0, pool=30.0
            ),
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
        """发送流式对话补全请求，内置指数退避重试。

        Args:
            num_ctx / think: Ollama 专有参数，其他协议实现忽略。
            num_predict: 最大输出 token 数。
            timeout: 覆盖默认读取超时（秒），用于大文本 prompt 评估耗时较长的场景。
        """
        max_attempts = 1 + self._max_retries
        last_error: Exception | None = None

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
            except httpx.HTTPError as e:
                last_error = e
                if attempt >= max_attempts or not _is_retryable(e):
                    raise
                delay = self._retry_delay * (2 ** (attempt - 1))
                logger.warning(
                    "LLM attempt %d/%d failed, retry in %.1fs: %s",
                    attempt, max_attempts, delay, e,
                )
                await asyncio.sleep(delay)

        raise last_error or RuntimeError("LLM chat failed with no attempts")

    def _request_timeout(self, timeout: float | None) -> httpx.Timeout | object:
        if timeout is None:
            return httpx.USE_CLIENT_DEFAULT
        return httpx.Timeout(connect=30.0, read=timeout, write=30.0, pool=30.0)

    @abstractmethod
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
        """执行单次流式对话请求（不含重试）。"""

    @abstractmethod
    async def is_reachable(self) -> bool:
        """检查服务端是否可达。"""

    async def close(self) -> None:
        await self._client.aclose()
