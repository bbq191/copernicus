"""领域异常到 HTTP 响应的统一映射。

响应体在保持 `detail` 字段（前端与第三方已依赖）的基础上，增加机器可读的
`code` 与用于日志关联的 `request_id`。
"""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from copernicus.exceptions import (
    AudioNotFoundError,
    CopernicusError,
    InvalidIdentifierError,
    QueueFullError,
    ServiceNotConfiguredError,
    TaskBusyError,
    TaskNotFoundError,
)
from copernicus.request_context import REQUEST_ID_HEADER, SCOPE_KEY

logger = logging.getLogger(__name__)

# Starlette 按异常 MRO 匹配最具体的处理器，因此子类与父类的注册顺序无关
_ERROR_TABLE: dict[type[CopernicusError], tuple[int, str]] = {
    TaskNotFoundError: (404, "task_not_found"),
    AudioNotFoundError: (404, "media_not_found"),
    TaskBusyError: (409, "task_busy"),
    InvalidIdentifierError: (422, "invalid_identifier"),
    QueueFullError: (429, "queue_full"),
    ServiceNotConfiguredError: (503, "service_not_configured"),
    CopernicusError: (500, "internal_error"),
}


def _error_response(
    request: Request, status_code: int, code: str, detail: str
) -> JSONResponse:
    # 从 scope 读取而非 contextvar：兜底处理器运行在请求中间件栈之外，contextvar 已复位
    return JSONResponse(
        status_code=status_code,
        content={
            "detail": detail,
            "code": code,
            "request_id": request.scope.get(SCOPE_KEY, "-"),
        },
    )


def register_error_handlers(app: FastAPI) -> None:
    for exc_type, (status_code, code) in _ERROR_TABLE.items():
        app.add_exception_handler(exc_type, _make_handler(status_code, code))
    app.add_exception_handler(Exception, _unhandled_handler)


def _make_handler(status_code: int, code: str):
    async def handler(request: Request, exc: CopernicusError) -> JSONResponse:
        return _error_response(request, status_code, code, str(exc))

    return handler


async def _unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
    """兜底：内部错误只记录日志，不向客户端暴露异常内容。"""
    logger.error("Unhandled error on %s %s", request.method, request.url.path, exc_info=exc)
    response = _error_response(
        request, 500, "internal_error", "服务器内部错误，请携带 request_id 联系管理员"
    )
    # 该响应不经过 RequestIdMiddleware 的 send 包装，需自行补上响应头
    response.headers[REQUEST_ID_HEADER] = request.scope.get(SCOPE_KEY, "-")
    return response
