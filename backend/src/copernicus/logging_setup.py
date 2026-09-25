"""日志初始化：main.py（服务进程）与 run_dev.py（开发启动器）共用。

输出目的地优先级：
  1. COPERNICUS_LOG_FILE  由 run_dev.py 设置，reload 出的 worker 复用同一文件
  2. LOG_TO_FILE=true     直接用 uvicorn 命令时的兼容模式（每次启动新建文件；由 Settings 读取环境变量/.env）
  3. 都没有               生产环境，输出到 stderr 由 journald 接管
"""

import logging
import logging.config
import os
from datetime import datetime
from pathlib import Path

from copernicus.config import settings
from copernicus.request_context import install_log_record_factory

LOG_FORMAT = "%(asctime)s %(levelname)-8s [%(request_id)s] %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_UVICORN_LOGGERS = ("uvicorn", "uvicorn.access", "uvicorn.error")


def configure_logging(log_file: Path | None = None) -> None:
    """让日志带 request_id，并输出到 log_file（None 则输出到 stderr）。"""
    install_log_record_factory()  # 必须早于格式配置：格式串引用 request_id
    if log_file is None:
        logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, datefmt=DATE_FORMAT)
        return
    logging.config.dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"default": {"format": LOG_FORMAT, "datefmt": DATE_FORMAT}},
        "handlers": {
            "file": {
                "class": "logging.FileHandler",
                "filename": str(log_file),
                "encoding": "utf-8",
                "formatter": "default",
            }
        },
        "root": {"level": "INFO", "handlers": ["file"]},
        "loggers": {
            **{name: {"handlers": ["file"], "propagate": False, "level": "INFO"} for name in _UVICORN_LOGGERS},
            "watchfiles": {"handlers": ["file"], "propagate": False, "level": "WARNING"},
        },
    })


def setup_logging_from_environment() -> None:
    """按 COPERNICUS_LOG_FILE / LOG_TO_FILE 决定日志去向（见模块说明）。"""
    if log_file := os.environ.get("COPERNICUS_LOG_FILE"):
        configure_logging(Path(log_file))
    elif settings.log_to_file:
        log_dir = _BACKEND_DIR.parent / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        configure_logging(log_dir / f"{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.log")
    else:
        configure_logging(None)
