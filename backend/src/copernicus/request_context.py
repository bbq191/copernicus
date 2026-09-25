"""请求追踪：为每个请求分配 request id，写入响应头，并注入所有日志记录。"""

import logging
import re
import uuid
from contextvars import ContextVar

REQUEST_ID_HEADER = "X-Request-ID"
SCOPE_KEY = "request_id"

_NO_REQUEST = "-"
_request_id: ContextVar[str] = ContextVar("request_id", default=_NO_REQUEST)

# 只接受简单字符，防止调用方通过请求头向日志注入换行等内容
_VALID_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")


def get_request_id() -> str:
    return _request_id.get()


def install_log_record_factory() -> None:
    """让每条日志记录带上 request_id 属性（在请求上下文外为 "-"）。

    在请求内通过 asyncio.create_task 启动的后台任务会继承该上下文，
    因此任务日志也能关联到提交它的请求。
    """
    previous = logging.getLogRecordFactory()
    if getattr(previous, "_injects_request_id", False):
        return  # 幂等：避免重复安装导致工厂链越叠越长

    def factory(*args, **kwargs):
        record = previous(*args, **kwargs)
        record.request_id = get_request_id()
        return record

    factory._injects_request_id = True  # type: ignore[attr-defined]
    logging.setLogRecordFactory(factory)


class RequestIdMiddleware:
    """纯 ASGI 中间件（不缓冲响应体，兼容文件下载与流式响应）。"""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = dict(scope["headers"]).get(REQUEST_ID_HEADER.lower().encode(), b"")
        candidate = incoming.decode("latin-1")
        request_id = candidate if _VALID_ID.fullmatch(candidate) else uuid.uuid4().hex[:16]
        scope[SCOPE_KEY] = request_id  # 供位于中间件栈之外的错误处理器读取
        token = _request_id.set(request_id)

        async def send_with_header(message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((REQUEST_ID_HEADER.lower().encode(), request_id.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_header)
        finally:
            _request_id.reset(token)
