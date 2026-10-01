"""后台任务追踪：为任务协程注入 task_id，供日志关联（配套 request_context.py）。"""

import logging
from contextvars import ContextVar, Token

_NO_TASK = "-"
_task_id: ContextVar[str] = ContextVar("task_id", default=_NO_TASK)


def get_task_id() -> str:
    return _task_id.get()


def set_task_id(task_id: str) -> Token:
    return _task_id.set(task_id)


def reset_task_id(token: Token) -> None:
    _task_id.reset(token)


def install_log_record_factory() -> None:
    """让每条日志记录带上 task_id 属性（任务协程之外为 "-"）。

    请求内触发的任务（如合规审核）同时带 request_id 与 task_id；
    纯后台的音视频任务没有 request_id，只有 task_id。
    """
    previous = logging.getLogRecordFactory()
    if getattr(previous, "_injects_task_id", False):
        return  # 幂等：避免重复安装导致工厂链越叠越长

    def factory(*args, **kwargs):
        record = previous(*args, **kwargs)
        record.task_id = get_task_id()
        return record

    factory._injects_task_id = True  # type: ignore[attr-defined]
    logging.setLogRecordFactory(factory)
