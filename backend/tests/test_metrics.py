"""Prometheus 文本输出、HTTP 中间件与 /metrics 端点。"""

from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from copernicus import metrics
from copernicus.dependencies import get_model_manager, get_task_store
from copernicus.routers.metrics import router as metrics_router
from copernicus.schemas.task import TaskStatus


class TestPrimitives:
    def test_counter_renders_labels_sorted_and_escaped(self):
        c = metrics.Counter("x_total", "help")
        c.inc(route='/a"b', method="GET")
        c.inc(2, route='/a"b', method="GET")
        assert list(c.samples()) == [
            "# HELP x_total help",
            "# TYPE x_total counter",
            'x_total{method="GET",route="/a\\"b"} 3',
        ]

    def test_histogram_buckets_are_cumulative(self):
        h = metrics.Histogram("d_seconds", "help", buckets=(1, 10))
        for v in (0.5, 5, 5, 50):
            h.observe(v, kind="a")
        lines = list(h.samples())
        assert 'd_seconds_bucket{kind="a",le="1"} 1' in lines
        assert 'd_seconds_bucket{kind="a",le="10"} 3' in lines
        assert 'd_seconds_bucket{kind="a",le="+Inf"} 4' in lines
        assert 'd_seconds_count{kind="a"} 4' in lines
        assert 'd_seconds_sum{kind="a"} 60.5' in lines

    def test_gauge_evaluates_at_render_time(self):
        value = [1]
        g = metrics.Gauge("g", "help", lambda: [({"k": "v"}, value[0])])
        value[0] = 7
        assert 'g{k="v"} 7' in list(g.samples())


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(metrics.HttpMetricsMiddleware)

    @app.get("/items/{item_id}")
    def item(item_id: str):
        return {"id": item_id}

    store = MagicMock()
    store.count_by_status.return_value = {s.value: 0 for s in TaskStatus} | {"queued_asr": 2}
    store.get_task_stats.return_value = {"synthesis_running": 1}
    manager = MagicMock(loaded_models=["asr"], estimated_vram_gb=4.5)
    app.dependency_overrides[get_task_store] = lambda: store
    app.dependency_overrides[get_model_manager] = lambda: manager
    app.include_router(metrics_router)
    return app


class TestHttpMetrics:
    def test_requests_are_grouped_by_route_template(self):
        client = TestClient(_app())
        client.get("/items/aaa")
        client.get("/items/bbb")
        client.get("/nowhere")
        body = client.get("/metrics").text

        assert 'copernicus_http_requests_total{method="GET",route="/items/{item_id}",status="200"}' in body
        assert "/items/aaa" not in body  # 真实 URL 不进入标签
        assert 'route="unmatched",status="404"' in body

    def test_endpoint_exposes_runtime_gauges(self):
        r = TestClient(_app()).get("/metrics")
        assert r.headers["content-type"].startswith("text/plain")
        assert 'copernicus_tasks{status="queued_asr"} 2' in r.text
        assert 'copernicus_model_loaded{model="asr"} 1' in r.text
        assert "copernicus_vram_estimated_gb 4.5" in r.text
        assert "copernicus_synthesis_running 1" in r.text
