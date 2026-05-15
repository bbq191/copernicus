"""开发服务器启动脚本。

将 uvicorn（含 reloader 主进程）的所有日志写入带时间戳的文件，
终端不输出任何内容（仅打印一行日志文件路径）。

用法：
    python run_dev.py              # 默认 reload
    python run_dev.py --no-reload  # 关闭热重载
"""

import logging
import logging.config
import os
import sys
from datetime import datetime
from pathlib import Path

# 日志目录：backend/ 的上级目录（项目根）下的 logs/
_log_dir = Path(__file__).resolve().parent.parent / "logs"
_log_dir.mkdir(parents=True, exist_ok=True)
_log_file = _log_dir / f"{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.log"

# 通知 reload worker 复用同一文件，而非各自新建
os.environ["COPERNICUS_LOG_FILE"] = str(_log_file)

logging.config.dictConfig({
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "format": "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        }
    },
    "handlers": {
        "file": {
            "class": "logging.FileHandler",
            "filename": str(_log_file),
            "encoding": "utf-8",
            "formatter": "default",
        }
    },
    "root": {"level": "INFO", "handlers": ["file"]},
    "loggers": {
        "uvicorn":        {"handlers": ["file"], "propagate": False, "level": "INFO"},
        "uvicorn.access": {"handlers": ["file"], "propagate": False, "level": "INFO"},
        "uvicorn.error":  {"handlers": ["file"], "propagate": False, "level": "INFO"},
        "watchfiles":     {"handlers": ["file"], "propagate": False, "level": "WARNING"},
    },
})

# 唯一一行终端输出
print(f"[dev] logging → {_log_file}", flush=True)

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "copernicus.main:app",
        reload="--no-reload" not in sys.argv,
        log_config=None,  # 禁用 uvicorn 默认 dictConfig，沿用上面的配置
    )
