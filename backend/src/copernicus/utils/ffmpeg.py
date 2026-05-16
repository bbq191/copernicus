"""Async ffmpeg helper — supports clean cancellation on SIGINT."""

from __future__ import annotations

import asyncio


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
