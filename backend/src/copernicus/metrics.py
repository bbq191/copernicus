"""Prometheus 文本格式指标（不引入第三方依赖）。

只实现本服务用到的三种指标：计数器、直方图、抓取时才计算的仪表盘。
计数器与直方图只在事件循环线程里更新，无需加锁。

作者：afu
"""

from __future__ import annotations

import bisect
import time
from collections.abc import Callable, Iterable

CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"

# 覆盖从毫秒级接口到小时级转写任务
DURATION_BUCKETS_S: tuple[float, ...] = (0.01, 0.05, 0.25, 1, 5, 30, 120, 600, 1800, 3600)

Labels = tuple[tuple[str, str], ...]


def _fmt_labels(labels: Labels) -> str:
    if not labels:
        return ""
    body = ",".join(f'{k}="{_escape(v)}"' for k, v in labels)
    return "{" + body + "}"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _key(labels: dict[str, str]) -> Labels:
    return tuple(sorted(labels.items()))


class Counter:
    def __init__(self, name: str, help_text: str) -> None:
        self.name, self.help = name, help_text
        self._values: dict[Labels, float] = {}

    def inc(self, amount: float = 1.0, **labels: str) -> None:
        key = _key(labels)
        self._values[key] = self._values.get(key, 0.0) + amount

    def samples(self) -> Iterable[str]:
        yield f"# HELP {self.name} {self.help}"
        yield f"# TYPE {self.name} counter"
        for labels, value in sorted(self._values.items()):
            yield f"{self.name}{_fmt_labels(labels)} {value:g}"


class Histogram:
    def __init__(self, name: str, help_text: str, buckets: tuple[float, ...] = DURATION_BUCKETS_S) -> None:
        self.name, self.help, self._bounds = name, help_text, buckets
        # 每个标签组合：各桶的非累计计数（最后一格是 +Inf）、总和
        self._counts: dict[Labels, list[int]] = {}
        self._sums: dict[Labels, float] = {}

    def observe(self, value: float, **labels: str) -> None:
        key = _key(labels)
        counts = self._counts.setdefault(key, [0] * (len(self._bounds) + 1))
        counts[bisect.bisect_left(self._bounds, value)] += 1
        self._sums[key] = self._sums.get(key, 0.0) + value

    def samples(self) -> Iterable[str]:
        yield f"# HELP {self.name} {self.help}"
        yield f"# TYPE {self.name} histogram"
        for labels, counts in sorted(self._counts.items()):
            cumulative = 0
            for bound, n in zip((*self._bounds, float("inf")), counts, strict=True):
                cumulative += n
                le = "+Inf" if bound == float("inf") else f"{bound:g}"
                yield f"{self.name}_bucket{_fmt_labels((*labels, ('le', le)))} {cumulative}"
            yield f"{self.name}_sum{_fmt_labels(labels)} {self._sums[labels]:g}"
            yield f"{self.name}_count{_fmt_labels(labels)} {cumulative}"


class Gauge:
    """抓取时才取值的仪表盘：`collect` 返回 [(标签, 值), ...]。"""

    def __init__(
        self, name: str, help_text: str, collect: Callable[[], list[tuple[dict[str, str], float]]]
    ) -> None:
        self.name, self.help, self._collect = name, help_text, collect

    def samples(self) -> Iterable[str]:
        yield f"# HELP {self.name} {self.help}"
        yield f"# TYPE {self.name} gauge"
        for labels, value in self._collect():
            yield f"{self.name}{_fmt_labels(_key(labels))} {value:g}"


class Registry:
    def __init__(self) -> None:
        self._metrics: list[Counter | Histogram | Gauge] = []

    def register(self, metric):
        self._metrics.append(metric)
        return metric

    def render(self, extra: Iterable[Gauge] = ()) -> str:
        lines = [line for m in (*self._metrics, *extra) for line in m.samples()]
        return "\n".join(lines) + "\n"


registry = Registry()

http_requests = registry.register(
    Counter("copernicus_http_requests_total", "HTTP 请求数（按路由模板、方法、状态码）")
)
http_duration = registry.register(
    Histogram("copernicus_http_request_duration_seconds", "HTTP 请求耗时（按路由模板、方法）")
)
tasks_finished = registry.register(
    Counter("copernicus_tasks_finished_total", "已结束的任务数（outcome=completed|failed）")
)
task_duration = registry.register(
    Histogram("copernicus_task_duration_seconds", "任务从提交到结束的耗时（含排队）")
)


class HttpMetricsMiddleware:
    """按"路由模板"（而不是真实 URL，避免任务号撑爆标签数量）统计请求数与耗时。纯 ASGI，不缓冲响应体。"""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        status = 500  # 应用抛出未处理异常时，响应由更外层的服务器生成
        start = time.perf_counter()

        async def send_capturing_status(message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_capturing_status)
        finally:
            route = scope.get("route")  # 路由匹配后由 Starlette 写入 scope
            path = getattr(route, "path", None) or "unmatched"  # 404 等未匹配请求归为一类
            method = scope["method"]
            http_requests.inc(method=method, route=path, status=str(status))
            http_duration.observe(time.perf_counter() - start, method=method, route=path)
