"""服务启动预检：验证本地模型文件完整性与外部服务可达性。

所有检查均为警告级别（不阻止启动），以显著分隔线在日志中标记，
方便运维快速定位配置缺失或服务不通的问题。
"""

import logging
from pathlib import Path
from urllib.parse import urlparse

from copernicus.config import Settings

logger = logging.getLogger(__name__)

_LINE = "=" * 56


def _ok(msg: str) -> str:
    return f"  [ OK ] {msg}"


def _warn(msg: str) -> str:
    return f"  [WARN] {msg}"


def _skip(msg: str) -> str:
    return f"  [SKIP] {msg}"


def _check_tts_paths(settings: Settings) -> list[tuple[str, bool]]:
    try:
        import ChatTTS  # noqa: F401
        return [(_ok("ChatTTS package installed"), True)]
    except ImportError:
        return [(_warn("ChatTTS not installed — run: pip install ChatTTS"), False)]


def _check_face_model(settings: Settings) -> list[tuple[str, bool]]:
    if not settings.face_detect_enabled:
        return [(_skip("Face detection disabled, YOLO check skipped"), True)]

    model = Path(settings.face_detect_model)
    if model.exists():
        return [(_ok(f"YOLO face model : {model}"), True)]
    return [(_warn(f"YOLO face model missing : {model}"), False)]


async def _check_llm(settings: Settings) -> list[tuple[str, bool]]:
    import httpx

    base_url = settings.llm_base_url.rstrip("/")
    # 与 OllamaClient 保持一致：去掉 /v1 后缀
    if base_url.endswith("/v1"):
        base_url = base_url[:-3]

    hostname = urlparse(base_url).hostname or ""
    is_local = hostname in ("localhost", "127.0.0.1", "::1", "0.0.0.0")

    if is_local:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{base_url}/api/tags")
            if resp.status_code == 200:
                return [(_ok(f"Ollama reachable : {base_url}  model={settings.llm_model_name}"), True)]
            return [(_warn(f"Ollama HTTP {resp.status_code} : {base_url}"), False)]
        except Exception as exc:
            return [(_warn(f"Ollama not reachable : {base_url}  ({exc})"), False)]
    else:
        if not settings.llm_api_key:
            return [(_warn(f"LLM API key empty for external service : {base_url}"), False)]
        return [(_ok(f"LLM API key set : {base_url}  model={settings.llm_model_name}"), True)]


def _check_funasr_patches() -> list[tuple[str, bool]]:
    try:
        import funasr
        funasr_root = Path(funasr.__file__).parent
    except ImportError:
        return [(_skip("FunASR not installed — patch check skipped"), True)]

    checks = [
        (
            funasr_root / "models" / "paraformer" / "model.py",
            "# Compute per-token confidence (am_scores is log_softmax, exp to get probabilities)",
            "paraformer :: token_confidence",
        ),
        (
            funasr_root / "models" / "seaco_paraformer" / "model.py",
            "# hotword (with cache to avoid repeated parsing across VAD segments)",
            "seaco_paraformer :: hotword cache",
        ),
        (
            funasr_root / "models" / "seaco_paraformer" / "model.py",
            'result_i["token_confidence"] = _token_confidence',
            "seaco_paraformer :: token_confidence",
        ),
    ]

    items: list[tuple[str, bool]] = []
    for path, marker, label in checks:
        try:
            applied = marker in path.read_text(encoding="utf-8")
        except OSError:
            items.append((_warn(f"FunASR patch file not found : {path.name}"), False))
            continue
        if applied:
            items.append((_ok(f"FunASR patch : {label}"), True))
        else:
            items.append((
                _warn(f"FunASR patch MISSING : {label}  →  python scripts/patch_funasr.py"),
                False,
            ))
    return items


async def run_preflight(settings: Settings) -> int:
    """运行全部预检，返回警告数量。结果以显著分隔线输出到日志。"""
    items = (
        _check_funasr_patches()
        + _check_tts_paths(settings)
        + _check_face_model(settings)
        + await _check_llm(settings)
    )

    warnings = sum(1 for _, ok in items if not ok)
    status = "ALL OK" if warnings == 0 else f"{warnings} WARNING(S)"

    logger.info(_LINE)
    logger.info("  COPERNICUS PREFLIGHT CHECK")
    logger.info(_LINE)
    for line, ok in items:
        (logger.info if ok else logger.warning)(line)
    end_log = logger.info if warnings == 0 else logger.warning
    end_log(_LINE)
    end_log("  PREFLIGHT DONE — %s", status)
    end_log(_LINE)

    return warnings
