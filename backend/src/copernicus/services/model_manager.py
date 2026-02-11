"""GPU model lifecycle manager.

Manages mutually-exclusive loading of heavy models (OCR, YOLO, etc.)
on a single GPU with limited VRAM.  ASR is assumed to be always-resident
and is **not** managed here.

Phase 0: skeleton + interface only.  Concrete loaders will be registered
in Phase 2 (OCR) and Phase 3 (YOLO).

Author: afu
"""

import asyncio
import gc
import logging
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any

logger = logging.getLogger(__name__)


class ModelManager:
    """Async-safe, single-GPU model loader/unloader."""

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
        """Register a model's load/unload functions (plugin-style)."""
        self._loaders[model_type] = loader
        if unloader:
            self._unloaders[model_type] = unloader

    @asynccontextmanager
    async def acquire(self, model_type: str):
        """Load *model_type*, unloading others first if needed.

        Usage::

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
        """Explicitly unload a model and free VRAM."""
        async with self._lock:
            await self._do_unload(model_type)

    async def unload_all(self) -> None:
        """Unload every managed model."""
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
