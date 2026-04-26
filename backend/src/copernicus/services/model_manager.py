"""GPU 模型生命周期管理器。

在显存受限的单 GPU 上管理重型模型（OCR、YOLO 等）的互斥加载。
ASR 模型假定常驻显存，不在此处管理。

Phase 0：仅骨架和接口定义。具体加载器将在
Phase 2（OCR）和 Phase 3（YOLO）中注册。

作者：afu
"""

import asyncio
import gc
import logging
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any

logger = logging.getLogger(__name__)


class ModelManager:
    """异步安全的单 GPU 模型加载/卸载管理器。"""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._loaded: dict[str, Any] = {}
        self._loaders: dict[str, Callable[[], Any]] = {}
        self._unloaders: dict[str, Callable[[Any], None]] = {}

    def register_loader(
        self,
        model_type: str,
        loader: Callable[[], Any],
        unloader: Callable[[Any], None] | None = None,
    ) -> None:
        """注册模型的加载/卸载函数（插件式）。"""
        self._loaders[model_type] = loader
        if unloader:
            self._unloaders[model_type] = unloader

    @asynccontextmanager
    async def acquire(self, model_type: str):
        """加载指定 model_type，必要时先卸载其他模型。

        用法::

            async with manager.acquire("ocr") as model:
                result = model.predict(image)
        """
        async with self._lock:
            # Unload other models to free VRAM
            for name in list(self._loaded):
                if name != model_type:
                    await self._do_unload(name)

            # Load requested model if not already loaded
            if model_type not in self._loaded:
                await self._do_load(model_type)

        try:
            yield self._loaded[model_type]
        finally:
            # Model stays loaded for short-term reuse.
            # Explicit unload() can be called to free VRAM immediately.
            pass

    async def unload(self, model_type: str) -> None:
        """显式卸载指定模型并释放显存。"""
        async with self._lock:
            await self._do_unload(model_type)

    async def unload_all(self) -> None:
        """卸载所有托管模型。"""
        async with self._lock:
            for name in list(self._loaded):
                await self._do_unload(name)

    # -- internal --------------------------------------------------------

    async def _do_load(self, model_type: str) -> None:
        loader = self._loaders.get(model_type)
        if loader is None:
            raise ValueError(f"No loader registered for model type '{model_type}'")

        logger.info("Loading model '%s' ...", model_type)
        model = await asyncio.to_thread(loader)
        self._loaded[model_type] = model
        logger.info("Model '%s' loaded.", model_type)

    async def _do_unload(self, model_type: str) -> None:
        model = self._loaded.pop(model_type, None)
        if model is None:
            return

        logger.info("Unloading model '%s' ...", model_type)
        unloader = self._unloaders.get(model_type)
        if unloader:
            await asyncio.to_thread(unloader, model)
        del model

        try:
            import torch
            torch.cuda.empty_cache()
        except ImportError:
            pass

        gc.collect()
        logger.info("Model '%s' unloaded.", model_type)
