"""LLM 客户端包：按 ``LLM_PROVIDER`` 选择 Ollama 原生或 OpenAI 兼容协议。"""

from copernicus.config import Settings
from copernicus.services.llm.base import ChatResponse, LLMClient
from copernicus.services.llm.ollama import OllamaClient
from copernicus.services.llm.openai_compat import OpenAICompatClient

__all__ = [
    "ChatResponse",
    "LLMClient",
    "OllamaClient",
    "OpenAICompatClient",
    "create_llm_client",
]


def create_llm_client(settings: Settings) -> LLMClient:
    if settings.llm_provider == "openai":
        return OpenAICompatClient.from_settings(settings)
    return OllamaClient.from_settings(settings)
