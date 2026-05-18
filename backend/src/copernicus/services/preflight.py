"""服务启动预检：验证本地模型文件完整性与外部服务可达性。

所有检查均为警告级别（不阻止启动），以显著分隔线在日志中标记，
方便运维快速定位配置缺失或服务不通的问题。
"""

import logging
import os
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


def _is_modelscope_cached(cache_root: Path, model_id: str) -> bool:
    return (cache_root / "models" / model_id).exists()


def _check_asr_models(settings: Settings) -> list[tuple[str, bool]]:
    cache_root = Path(os.environ.get("MODELSCOPE_CACHE", str(settings.funasr_cache_dir)))

    if settings.asr_mode == "sensevoice":
        mid = settings.sensevoice_model_dir
        if _is_modelscope_cached(cache_root, mid):
            return [(_ok(f"SenseVoice model  : {mid}"), True)]
        return [(_warn(
            f"SenseVoice model missing : {cache_root / 'models' / mid}"
            "  — run: python scripts/download_models.py"
        ), False)]

    # paraformer 模式：需要 4 个模型
    model_ids = [
        (settings.asr_model_dir,  "seaco_paraformer"),
        (settings.vad_model_dir,  "VAD"),
        (settings.punc_model_dir, "punctuation"),
        (settings.spk_model_dir,  "speaker embedding"),
    ]
    items: list[tuple[str, bool]] = []
    for mid, label in model_ids:
        if _is_modelscope_cached(cache_root, mid):
            items.append((_ok(f"ASR model [{label}] : {mid}"), True))
        else:
            items.append((_warn(
                f"ASR model [{label}] missing : {cache_root / 'models' / mid}"
                "  — run: python scripts/download_models.py"
            ), False))
    return items


def _check_tts_paths(settings: Settings) -> list[tuple[str, bool]]:
    results: list[tuple[str, bool]] = []
    try:
        import ChatTTS  # noqa: F401
        results.append((_ok("ChatTTS package installed"), True))
    except ImportError:
        results.append((_warn("ChatTTS not installed — run: pip install ChatTTS"), False))
    chattts_dir = settings.chattts_model_dir
    if chattts_dir.exists() and any(chattts_dir.glob("*.safetensors")):
        results.append((_ok(f"ChatTTS weights : {chattts_dir}"), True))
    else:
        results.append((_warn(f"ChatTTS weights missing : {chattts_dir}"), False))
    return results


def _check_face_model(settings: Settings) -> list[tuple[str, bool]]:
    if not settings.face_detect_enabled:
        return [(_skip("Face detection disabled, YOLO check skipped"), True)]

    model = settings.yolo_model_path
    if model.exists():
        return [(_ok(f"YOLO face model : {model}"), True)]
    return [(_warn(f"YOLO face model missing : {model}  — place yolov8n-face.pt in backend/models/yolo/"), False)]


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
            if resp.status_code != 200:
                return [(_warn(f"Ollama HTTP {resp.status_code} : {base_url}"), False)]
            installed = {m["name"] for m in (resp.json().get("models") or [])}
            target = settings.llm_model_name
            # 精确匹配或前缀匹配（"qwen3:latest" 匹配 "qwen3"）
            found = target in installed or any(n.startswith(target.split(":")[0]) for n in installed)
            if found:
                return [(_ok(f"Ollama reachable, model found : {target}"), True)]
            available = ", ".join(sorted(installed)) or "(none)"
            return [(_warn(
                f"Ollama model not found : '{target}'  — run: ollama pull {target}"
                f"  (installed: {available})"
            ), False)]
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
        + _check_asr_models(settings)
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
