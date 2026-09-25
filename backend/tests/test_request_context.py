import logging
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from copernicus.error_handlers import register_error_handlers
from copernicus.exceptions import QueueFullError, TaskNotFoundError
from copernicus.request_context import (
    REQUEST_ID_HEADER,
    RequestIdMiddleware,
    get_request_id,
    install_log_record_factory,
)
from copernicus.routers.transcription import router as health_router


@pytest.fixture
def app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)
    register_error_handlers(app)

    @app.get("/ok")
    async def ok():
        return {"request_id": get_request_id()}

    @app.get("/log")
    async def log_something():
        logging.getLogger("probe").info("inside request")
        return {}

    @app.get("/missing")
    async def missing():
        raise TaskNotFoundError("Task x not found")

    @app.get("/full")
    async def full():
        raise QueueFullError("队列已满")

    @app.get("/boom")
    async def boom():
        raise RuntimeError("secret internal detail: db password=hunter2")

    @app.get("/http")
    async def http_error():
        raise HTTPException(status_code=418, detail="teapot")

    app.include_router(health_router)
    return app


@pytest.fixture
def client(app) -> TestClient:
    # raise_server_exceptions=False：让兜底处理器生成 500 响应而不是把异常抛给测试
    return TestClient(app, raise_server_exceptions=False)


class TestRequestId:
    def test_generated_and_returned_in_header(self, client):
        r = client.get("/ok")
        assert r.headers[REQUEST_ID_HEADER]
        assert r.json()["request_id"] == r.headers[REQUEST_ID_HEADER]

    def test_valid_incoming_id_is_propagated(self, client):
        r = client.get("/ok", headers={REQUEST_ID_HEADER: "trace-abc.123"})
        assert r.headers[REQUEST_ID_HEADER] == "trace-abc.123"

    @pytest.mark.parametrize("bad", ["a b", "x" * 65, "a;b", "a\tb"])
    def test_invalid_incoming_id_replaced(self, client, bad):
        r = client.get("/ok", headers={REQUEST_ID_HEADER: bad})
        assert r.headers[REQUEST_ID_HEADER] != bad
        assert len(r.headers[REQUEST_ID_HEADER]) == 16

    def test_context_reset_after_request(self, client):
        client.get("/ok")
        assert get_request_id() == "-"

    def test_log_records_inside_request_carry_its_id(self, client, caplog):
        install_log_record_factory()
        with caplog.at_level(logging.INFO, logger="probe"):
            r = client.get("/log", headers={REQUEST_ID_HEADER: "rid-log"})

        inside = [rec for rec in caplog.records if rec.name == "probe"]
        assert inside and inside[0].request_id == "rid-log"
        assert r.headers[REQUEST_ID_HEADER] == "rid-log"

    def test_log_records_outside_request_use_placeholder(self, caplog):
        install_log_record_factory()
        with caplog.at_level(logging.INFO):
            logging.getLogger("probe2").info("outside")
        assert caplog.records[-1].request_id == "-"


class TestErrorBodies:
    def test_domain_error_has_code_and_request_id(self, client):
        r = client.get("/missing", headers={REQUEST_ID_HEADER: "rid-1"})
        assert r.status_code == 404
        assert r.json() == {
            "detail": "Task x not found",
            "code": "task_not_found",
            "request_id": "rid-1",
        }
        # 只出现一个响应头，不重复
        assert r.headers.get_list(REQUEST_ID_HEADER) == ["rid-1"]

    def test_queue_full_is_429(self, client):
        r = client.get("/full")
        assert r.status_code == 429
        assert r.json()["code"] == "queue_full"

    def test_unhandled_error_does_not_leak_message(self, client):
        r = client.get("/boom", headers={REQUEST_ID_HEADER: "rid-2"})
        assert r.status_code == 500
        body = r.json()
        assert "hunter2" not in r.text
        assert body["code"] == "internal_error"
        assert body["request_id"] == "rid-2"
        assert r.headers[REQUEST_ID_HEADER] == "rid-2"

    def test_http_exception_keeps_detail_shape_and_gets_header(self, client):
        r = client.get("/http")
        assert r.status_code == 418
        assert r.json() == {"detail": "teapot"}
        assert r.headers[REQUEST_ID_HEADER]


class TestLiveness:
    def test_liveness_needs_no_dependencies(self, client):
        # 未挂载 pipeline / task_store，也应返回 200
        r = client.get("/api/v1/health/live")
        assert r.status_code == 200
        assert r.json() == {"status": "alive"}
