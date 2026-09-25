"""Async ffmpeg helper — supports clean cancellation on SIGINT."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path


async def run(cmd: list[str], timeout: float = 600) -> tuple[int, str]:
    """Run ffmpeg as a native asyncio subprocess.

    Returns (returncode, stderr). Kills the process on cancellation or timeout
    so the service can shut down immediately on Ctrl+C.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        raise RuntimeError("ffmpeg not found — install ffmpeg and add it to PATH.")

    try:
        _, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        proc.kill()
        await proc.wait()
        raise

    return proc.returncode, stderr_bytes.decode(errors="replace")


_DURATION = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")


def parse_duration_s(stderr: str) -> float | None:
    """从 `ffmpeg -i` 的 stderr 中解析媒体时长（秒）；没有时长信息（如直播流）返回 None。"""
    m = _DURATION.search(stderr)
    if m is None:
        return None
    hours, minutes, seconds = m.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


async def probe_duration_s(path: Path | str) -> float | None:
    """只依赖 ffmpeg 本体读取时长（不额外要求 ffprobe）。失败时返回 None，由调用方降级。"""
    try:
        # 不带输出文件时 ffmpeg 会以非零码退出，但仍会打印输入信息
        _, stderr = await run(["ffmpeg", "-hide_banner", "-i", str(path)], timeout=60)
    except (RuntimeError, asyncio.TimeoutError):
        return None
    return parse_duration_s(stderr)
