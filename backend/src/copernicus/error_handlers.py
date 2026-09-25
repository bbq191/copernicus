"""领域异常到 HTTP 状态码的统一映射。"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from copernicus.exceptions import (
    AudioNotFoundError,
    CopernicusError,
    InvalidIdentifierError,
    ServiceNotConfiguredError,
    TaskBusyError,
    TaskNotFoundError,
)

# Starlette 按异常 MRO 匹配最具体的处理器，因此子类与父类的注册顺序无关
_STATUS_BY_EXCEPTION: dict[type[CopernicusError], int] = {
    TaskNotFoundError: 404,
    AudioNotFoundError: 404,
    TaskBusyError: 409,
    InvalidIdentifierError: 422,
    ServiceNotConfiguredError: 503,
    CopernicusError: 500,
}


def register_error_handlers(app: FastAPI) -> None:
    for exc_type, status_code in _STATUS_BY_EXCEPTION.items():
        app.add_exception_handler(exc_type, _make_handler(status_code))


def _make_handler(status_code: int):
    async def handler(request: Request, exc: CopernicusError) -> JSONResponse:
        return JSONResponse(status_code=status_code, content={"detail": str(exc)})

    return handler
