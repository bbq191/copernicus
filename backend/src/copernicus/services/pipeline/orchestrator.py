"""Pipeline 编排器：按序执行各 Stage 并上报进度。"""

import logging
import time

from copernicus.services.pipeline.base import (
    PipelineContext,
    ProgressCallback,
    Stage,
    StageProgressCallback,
)

logger = logging.getLogger(__name__)


class PipelineOrchestrator:
    """顺序执行 Stage 列表，跳过 should_run 返回 False 的阶段。"""

    def __init__(self) -> None:
        self._stages: list[Stage] = []

    def register(self, stage: Stage) -> "PipelineOrchestrator":
        self._stages.append(stage)
        return self

    async def run(
        self,
        ctx: PipelineContext,
        on_stage_progress: StageProgressCallback | None = None,
    ) -> PipelineContext:
        total = len(self._stages)
        executed = 0

        for stage in self._stages:
            if not stage.should_run(ctx):
                logger.debug("Stage %s skipped (should_run=False)", stage.name)
                continue

            executed += 1
            logger.info("Stage [%d/%d] %s starting...", executed, total, stage.name)

            # Build a per-stage progress callback that forwards to the outer callback
            stage_progress: ProgressCallback | None = None
            if on_stage_progress:
                def _make_cb(name: str, idx: int) -> ProgressCallback:
                    def _cb(current: int, total_items: int) -> None:
                        on_stage_progress(name, idx, total, current, total_items)
                    return _cb
                stage_progress = _make_cb(stage.name, executed - 1)

            start = time.perf_counter()
            try:
                ctx = await stage.execute(ctx, on_progress=stage_progress)
            except Exception as exc:
                raise RuntimeError(f"[stage:{stage.name}] {exc}") from exc
            elapsed = (time.perf_counter() - start) * 1000
            ctx.processing_times[stage.name] = elapsed

            logger.info(
                "Stage [%d/%d] %s completed in %.0fms",
                executed, total, stage.name, elapsed,
            )

        return ctx
