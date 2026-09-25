"""FunASR 模型加载辅助：缓存检测、下载心跳日志与统一的"加载并计时"流程。"""

import contextlib
import logging
import os
import threading
import time
from pathlib import Path

from copernicus.config import settings as _settings

logger = logging.getLogger(__name__)

_MODELSCOPE_CACHE = Path(
    os.environ.get("MODELSCOPE_CACHE", str(_settings.funasr_cache_dir))
)


def is_modelscope_cached(model_id: str) -> bool:
    """检查 ModelScope 模型是否已在本地缓存（路径格式：{cache}/models/{org}/{name}）。"""
    return (_MODELSCOPE_CACHE / "models" / model_id).exists()


class DownloadHeartbeat:
    """后台线程：下载期间每隔 interval 秒向日志写入进度心跳。

    使用方式：
        with DownloadHeartbeat(model_ids, logger.info, interval=30):
            model = AutoModel(...)
    """

    def __init__(self, model_ids: list[str], log_fn, interval: int = 30) -> None:
        self._model_ids = model_ids
        self._log_fn = log_fn
        self._interval = interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._beat, daemon=True)

    def _beat(self) -> None:
        elapsed = 0
        while not self._stop.wait(self._interval):
            elapsed += self._interval
            for mid in self._model_ids:
                self._log_fn("  [DOWNLOAD] %s — %ds elapsed ...", mid, elapsed)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *_):
        self._stop.set()
        self._thread.join(timeout=1)


def load_automodel(model_kwargs: dict, model_ids: list[str], label: str):
    """加载一个 FunASR AutoModel；缓存缺失时先提示将下载，并在下载期间输出心跳日志。

    model_ids: 本次加载涉及的全部 ModelScope 模型 id（用于判断缺失哪些）。
    """
    from funasr import AutoModel

    missing = [mid for mid in model_ids if not is_modelscope_cached(mid)]
    if missing:
        logger.info("=" * 60)
        logger.info("  [DOWNLOAD] %s models not in cache — downloading now", label)
        for mid in missing:
            logger.info("  [DOWNLOAD] %s", mid)
        logger.info("  [DOWNLOAD] This may take several minutes ...")
        logger.info("=" * 60)

    started = time.monotonic()
    guard = DownloadHeartbeat(missing, logger.info) if missing else contextlib.nullcontext()
    with guard:
        model = AutoModel(**model_kwargs)
    elapsed = time.monotonic() - started

    if missing:
        logger.info("  [DOWNLOAD] Complete — %s ready in %.1fs", label, elapsed)
    else:
        logger.info("%s loaded from cache in %.1fs", label, elapsed)
    return model
