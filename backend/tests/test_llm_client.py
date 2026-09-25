import json

import httpx
import pytest

from copernicus.config import Settings
from copernicus.services.llm import (
    OllamaClient,
    OpenAICompatClient,
    create_llm_client,
)


def _settings(**overrides) -> Settings:
    base = dict(
        llm_provider="openai",
        llm_api_key="sk-test",
        llm_base_url="https://api.example.com",
        llm_model_name="test-model",
        llm_max_retries=2,
        llm_retry_delay=0.0,
    )
    return Settings(**{**base, **overrides})


def _sse(*events: dict | str) -> str:
    lines = [
        e if isinstance(e, str) else json.dumps(e, ensure_ascii=False) for e in events
    ]
    return "".join(f"data: {line}\n\n" for line in lines)


def _use_transport(client, handler) -> None:
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))


class TestFactory:
    def test_default_provider_is_ollama(self):
        client = create_llm_client(_settings(llm_provider="ollama"))
        assert isinstance(client, OllamaClient)

    def test_openai_provider(self):
        client = create_llm_client(_settings())
        assert isinstance(client, OpenAICompatClient)

    def test_ollama_strips_v1_suffix(self):
        client = create_llm_client(
            _settings(llm_provider="ollama", llm_base_url="http://localhost:11434/v1")
        )
        assert client._base_url == "http://localhost:11434"


class TestOpenAICompat:
    async def test_streams_content_and_usage(self):
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["payload"] = json.loads(request.content)
            body = _sse(
                {"model": "m1", "choices": [{"delta": {"content": "你好"}}]},
                {"choices": [{"delta": {"content": "世界"}}]},
                {"choices": [], "usage": {"completion_tokens": 7}},
                "[DONE]",
            )
            return httpx.Response(200, text=body)

        client = OpenAICompatClient.from_settings(_settings())
        _use_transport(client, handler)

        resp = await client.chat(
            [{"role": "user", "content": "hi"}], json_format=True, num_predict=64
        )

        assert resp.content == "你好世界"
        assert resp.model == "m1"
        assert resp.eval_count == 7
        assert seen["url"] == "https://api.example.com/chat/completions"
        assert seen["payload"]["response_format"] == {"type": "json_object"}
        assert seen["payload"]["max_tokens"] == 64
        await client.close()

    async def test_sends_bearer_header(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["auth"] = request.headers.get("authorization")
            return httpx.Response(200, text=_sse("[DONE]"))

        client = OpenAICompatClient.from_settings(_settings())
        # 构造时注入的 headers 位于原 client 上，需沿用其 headers 到 mock client
        headers = dict(client._client.headers)
        client._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), headers=headers
        )

        await client.chat([{"role": "user", "content": "hi"}])
        assert captured["auth"] == "Bearer sk-test"
        await client.close()


class TestRetryPolicy:
    async def test_retries_on_5xx_then_succeeds(self):
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] < 3:
                return httpx.Response(503)
            return httpx.Response(
                200, text=_sse({"choices": [{"delta": {"content": "ok"}}]}, "[DONE]")
            )

        client = OpenAICompatClient.from_settings(_settings())
        _use_transport(client, handler)

        resp = await client.chat([{"role": "user", "content": "hi"}])
        assert resp.content == "ok"
        assert calls["n"] == 3
        await client.close()

    async def test_does_not_retry_on_401(self):
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(401)

        client = OpenAICompatClient.from_settings(_settings())
        _use_transport(client, handler)

        with pytest.raises(httpx.HTTPStatusError):
            await client.chat([{"role": "user", "content": "hi"}])
        assert calls["n"] == 1
        await client.close()


class TestOllama:
    async def test_streams_ndjson(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/chat"
            lines = [
                {"message": {"content": "甲"}},
                {"message": {"content": "乙"}, "done": True, "model": "q", "eval_count": 3},
            ]
            return httpx.Response(200, text="\n".join(json.dumps(x) for x in lines))

        client = OllamaClient.from_settings(_settings(llm_provider="ollama"))
        _use_transport(client, handler)

        resp = await client.chat([{"role": "user", "content": "hi"}])
        assert resp.content == "甲乙"
        assert resp.eval_count == 3
        await client.close()
