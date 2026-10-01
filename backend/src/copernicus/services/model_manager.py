"""GPU 模型生命周期管理器。

单 GPU 显存有限，ASR、TTS 等重型模型不能同时常驻。本模块保证两件事：

1. 使用期间不会被卸载：`use()` 持有该模型的使用锁，`unload()` 必须等锁释放。
   （否则转写任务正在跑、或在排队等 GPU 时，模型被卸载会得到 None 并失败。）
2. 互斥加载：`use(..., exclusive=True)` 先卸载其他模型再加载自己，等待它们的使用者结束。

使用锁是每个模型一把、按 FIFO 排队；只允许一个模型以 exclusive 方式获取（当前只有 TTS），
因为两个 exclusive 使用者会互相等待对方的锁。

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
        self._loaded: dict[str, Any] = {}
        self._loaders: dict[str, Callable[[], Any]] = {}
        self._unloaders: dict[str, Callable[[Any], None]] = {}
        self._vram_estimates: dict[str, float] = {}
        self._use_locks: dict[str, asyncio.Lock] = {}
        self._waiters: dict[str, list[str]] = {}  # model_type -> 正在等待该锁的 ticket，按到达顺序

    def register_loader(
        self,
        model_type: str,
        loader: Callable[[], Any],
        unloader: Callable[[Any], None] | None = None,
        vram_estimate_gb: float = 0.0,
    ) -> None:
        """注册模型的加载/卸载函数（插件式）。"""
        self._loaders[model_type] = loader
        if unloader:
            self._unloaders[model_type] = unloader
        self._vram_estimates[model_type] = vram_estimate_gb

    def mark_loaded(self, model_type: str, model: Any) -> None:
        """标记某模型为已加载状态（用于外部初始化的模型，无需通过 loader）。"""
        self._loaded[model_type] = model

    @property
    def loaded_models(self) -> list[str]:
        return list(self._loaded)

    @property
    def estimated_vram_gb(self) -> float:
        return sum(self._vram_estimates.get(m, 0.0) for m in self._loaded)

    def _use_lock(self, model_type: str) -> asyncio.Lock:
        return self._use_locks.setdefault(model_type, asyncio.Lock())

    def is_busy(self, model_type: str) -> bool:
        """该模型当前是否被占用（新的使用者需要排队）。"""
        return self._use_lock(model_type).locked()

    def queue_position(self, model_type: str, ticket: str) -> int:
        """ticket 在该模型等待队列中前面还有几个；不在队列中（已拿到锁或从未排队）则为 0。"""
        return self._waiters.get(model_type, []).index(ticket) if ticket in self._waiters.get(model_type, []) else 0

    @asynccontextmanager
    async def use(
        self, model_type: str, *, exclusive: bool = False, unload_after: bool = False, ticket: str | None = None
    ):
        """独占使用指定模型；未加载则先加载。持有期间该模型不会被卸载。

        exclusive:    先卸载其他所有模型（会等它们的使用者结束）。
        unload_after: 使用结束后立即卸载本模型，释放显存（用于偶发、体积大的模型）。
        ticket:       传入后，排队等待期间可通过 queue_position(model_type, ticket) 查询排在第几位
                      （asyncio.Lock 按 FIFO 唤醒等待者，这里维护的等待列表与之同序）。

        用法::

            async with manager.use("asr") as model:
                await asyncio.to_thread(model.transcribe, ...)
        """
        lock = self._use_lock(model_type)
        queued = ticket is not None and lock.locked()
        if queued:
            self._waiters.setdefault(model_type, []).append(ticket)
        try:
            async with lock:
                if queued:
                    self._waiters[model_type].remove(ticket)
                    queued = False
                if exclusive:
                    for name in list(self._loaded):
                        if name != model_type:
                            await self.unload(name)
                if model_type not in self._loaded:
                    await self._do_load(model_type)
                try:
                    yield self._loaded[model_type]
                finally:
                    if unload_after:
                        await asyncio.shield(self._do_unload(model_type))
        finally:
            # 等待过程中被取消（如任务排队时被用户取消）时，锁内的移除不会执行，这里兜底清理
            if queued:
                waiters = self._waiters.get(model_type)
                if waiters and ticket in waiters:
                    waiters.remove(ticket)

    async def unload(self, model_type: str) -> None:
        """卸载指定模型并释放显存；模型正被使用时等待其结束。"""
        async with self._use_lock(model_type):
            await self._do_unload(model_type)

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
