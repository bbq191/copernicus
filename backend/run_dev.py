"""开发服务器启动脚本。

所有日志写入带时间戳的文件，终端静默。

用法：
    python run_dev.py              # 默认 reload
    python run_dev.py --no-reload  # 关闭热重载
"""

import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# 修复 Windows 下 joblib/loky 物理核心检测问题（必须在 joblib 导入前设置）
os.environ.setdefault("LOKY_MAX_CPU_COUNT", str(os.cpu_count() or 8))
os.environ.setdefault("OMP_NUM_THREADS", str(os.cpu_count() or 8))

# 允许 PyTorch 使用非连续显存段，防止多次推理后碎片化 OOM（必须在 torch 导入前设置）
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

from copernicus.logging_setup import configure_logging

_log_dir = Path(__file__).resolve().parent.parent / "logs"
_log_dir.mkdir(parents=True, exist_ok=True)

# 每8小时共用一个日志文件（槽：00 / 08 / 16），追加写入
_now = datetime.now()
_slot = _now.hour // 8 * 8
_log_file = _log_dir / f"{_now.strftime('%Y-%m-%d')}_{_slot:02d}.log"

# 通知 reload worker 复用同一文件，而非各自新建
os.environ["COPERNICUS_LOG_FILE"] = str(_log_file)
configure_logging(_log_file)

_logger = logging.getLogger(__name__)
_logger.info("=== SERVER START === logging → %s", _log_file)

import uvicorn

if __name__ == "__main__":
    try:
        uvicorn.run(
            "copernicus.main:app",
            host="0.0.0.0",
            port=8000,
            reload="--no-reload" not in sys.argv,
            log_config=None,
        )
    finally:
        _logger.info("=== SERVER STOP ===")
