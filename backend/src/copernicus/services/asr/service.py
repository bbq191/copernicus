"""双模式 ASR 服务：Paraformer（一次推理含说话人）或 SenseVoice（抗噪，声纹聚类另做说话人分离）。

模型加载、文本清洗、分段构建与说话人分离分别在同包的其他模块中。
"""

import logging
from pathlib import Path

from copernicus.config import Settings
from copernicus.exceptions import ASRError
from copernicus.services.asr.diarization import SpeakerDiarizer
from copernicus.services.asr.model_loading import load_automodel
from copernicus.services.asr.segment_builders import (
    build_segments_from_sentence_info,
    build_segments_from_sentences,
    log_confidence_stats,
)
from copernicus.services.asr.text_cleanup import (
    clean_sensevoice_text,
    is_noise_segment,
    split_long_segment,
)
from copernicus.services.asr.types import ASRResult, Segment
from copernicus.utils.text import split_sentences

logger = logging.getLogger(__name__)

# ASR 推理常量
_PARAFORMER_VAD_MAX_SEGMENT_MS = 30000  # Paraformer VAD 单段最长时间
_PARAFORMER_MERGE_LENGTH_S = 60         # Paraformer 模型每次最长合并秒数
_SENSEVOICE_VAD_MAX_SEGMENT_MS = 15000  # SenseVoice VAD 单段最长时间
_SENSEVOICE_MERGE_LENGTH_S = 15         # SenseVoice 每段最长合并秒数
_SPK_BATCH_CAP = 60                     # 说话人分离模式 batch_size 上限（秒）


class ASRService:
    """双模式 ASR 服务：Paraformer (说话人分离) 或 SenseVoice (抗噪增强)"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings  # 保存配置用于热重载
        self._mode = settings.asr_mode
        self._batch_size = settings.asr_batch_size
        device = settings.resolve_asr_device()

        self._max_segment_ms = settings.sensevoice_max_segment_ms
        self._filter_noise = settings.filter_noise_segments
        self._diarizer = SpeakerDiarizer(
            window_ms=settings.spk_sliding_window_ms,
            step_ms=settings.spk_sliding_step_ms,
            threshold_ms=settings.spk_sliding_threshold_ms,
            distance_threshold=settings.spk_distance_threshold,
        )

        logger.info("=" * 60)
        logger.info("ASR MODE: %s", self._mode.upper())
        logger.info("Device: %s", device)
        logger.info("Batch size: %d", self._batch_size)
        logger.info("=" * 60)

        if self._mode == "sensevoice":
            self._init_sensevoice_mode(settings, device)
        else:
            self._init_paraformer_mode(settings, device)

        logger.info("ASR service initialized successfully in [%s] mode.", self._mode.upper())

    def _init_paraformer_mode(self, settings: Settings, device: str) -> None:
        """Paraformer 模式：ASR + VAD + PUNC + SPK 分离组合"""
        logger.info("Initializing Paraformer mode...")
        logger.info("  ASR model: %s", settings.asr_model_dir)

        model_kwargs: dict = {
            "model": settings.asr_model_dir,
            "device": device,
            "disable_update": True,
        }

        if settings.asr_disable_pbar:
            model_kwargs["disable_pbar"] = True

        if device.startswith("cuda") and settings.asr_dtype != "float32":
            model_kwargs["dtype"] = settings.asr_dtype
            logger.info("  FP16 enabled: dtype=%s", settings.asr_dtype)

        # VAD 模型 - 关键：控制切分参数防止 OOM
        if settings.vad_model_dir:
            model_kwargs["vad_model"] = settings.vad_model_dir
            model_kwargs["vad_kwargs"] = {
                "max_single_segment_time": _PARAFORMER_VAD_MAX_SEGMENT_MS,
            }
            logger.info("  VAD model: %s (max_segment=%dms)", settings.vad_model_dir, _PARAFORMER_VAD_MAX_SEGMENT_MS)

        if settings.punc_model_dir:
            model_kwargs["punc_model"] = settings.punc_model_dir
            logger.info("  PUNC model: %s", settings.punc_model_dir)

        if settings.spk_model_dir:
            model_kwargs["spk_model"] = settings.spk_model_dir
            logger.info("  SPK model: %s", settings.spk_model_dir)

        self._model = load_automodel(model_kwargs, settings.required_asr_model_ids, "Paraformer")
        self._has_spk = bool(settings.spk_model_dir)
        self._spk_model = None  # Paraformer 模式不需要单独的 spk_model

    def _init_sensevoice_mode(self, settings: Settings, device: str) -> None:
        """SenseVoice 解耦模式：ASR 和 SD 分离加载"""
        # ASR 模型 (SenseVoice) - 必须配合 VAD 使用才能切分
        asr_kwargs: dict = {
            "model": settings.sensevoice_model_dir,
            "device": device,
            "disable_update": True,
        }

        # VAD 配置 - 关键：限制单段最长时间，避免输出一整段长文
        if settings.vad_model_dir:
            asr_kwargs["vad_model"] = settings.vad_model_dir
            asr_kwargs["vad_kwargs"] = {
                "max_single_segment_time": _SENSEVOICE_VAD_MAX_SEGMENT_MS,
            }

        if settings.asr_disable_pbar:
            asr_kwargs["disable_pbar"] = True

        model_ids = [mid for mid in (settings.sensevoice_model_dir, settings.vad_model_dir) if mid]
        self._model = load_automodel(asr_kwargs, model_ids, "SenseVoice")
        self._sensevoice_language = settings.sensevoice_language

        # 声纹模型 (Campplus) - 用于解耦说话人分离
        if settings.spk_model_dir:
            spk_kwargs: dict = {
                "model": settings.spk_model_dir,
                "device": device,
                "disable_update": True,
            }
            if settings.asr_disable_pbar:
                spk_kwargs["disable_pbar"] = True
            self._spk_model = load_automodel(spk_kwargs, [settings.spk_model_dir], "SPK model")
            self._has_spk = True
        else:
            self._spk_model = None
            self._has_spk = False

    def transcribe(
        self,
        audio_path: Path,
        hotwords: list[str] | None = None,
        sentence_timestamp: bool = False,
    ) -> ASRResult:
        """Run ASR inference on a WAV file. This is a blocking call."""
        import gc
        logger.info("[%s] Starting transcription: %s", self._mode.upper(), audio_path.name)
        try:
            if self._mode == "sensevoice":
                return self._transcribe_sensevoice(audio_path, sentence_timestamp)
            else:
                return self._transcribe_paraformer(audio_path, hotwords, sentence_timestamp)
        except Exception as e:
            raise ASRError(f"ASR inference failed: {e}") from e
        finally:
            try:
                import torch
                torch.cuda.empty_cache()
            except Exception:
                pass
            gc.collect()

    def _transcribe_paraformer(
        self,
        audio_path: Path,
        hotwords: list[str] | None = None,
        sentence_timestamp: bool = False,
    ) -> ASRResult:
        """Paraformer 模式推理"""
        # 说话人分离需要更小的 batch_size 以避免 OOM
        # batch_size_s 表示每批处理的音频秒数，16GB 显存建议 60-120 秒
        effective_batch_size = min(self._batch_size, _SPK_BATCH_CAP) if self._has_spk else self._batch_size

        kwargs: dict = {
            "input": str(audio_path),
            "batch_size_s": effective_batch_size,
            "merge_vad": True,
            "merge_length_s": _PARAFORMER_MERGE_LENGTH_S,
        }
        if sentence_timestamp:
            kwargs["sentence_timestamp"] = True
        if hotwords:
            kwargs["hotword"] = " ".join(hotwords)
            logger.info("Using %d hotwords", len(hotwords))
        if self._has_spk and sentence_timestamp:
            kwargs["return_spk_res"] = True

        logger.info(
            "Paraformer generate params: batch_size_s=%d, merge_length_s=%d, "
            "sentence_timestamp=%s, return_spk_res=%s",
            effective_batch_size,
            kwargs.get("merge_length_s", 0),
            sentence_timestamp,
            kwargs.get("return_spk_res", False),
        )

        results = self._model.generate(**kwargs)

        if not results:
            logger.warning("Paraformer returned empty results")
            return ASRResult(text="")

        result = results[0]
        full_text = result.get("text", "")
        sentence_info: list[dict] = result.get("sentence_info", [])

        # 记录更多调试信息
        available_keys = list(result.keys())
        logger.info(
            "Paraformer result keys: %s, text_len=%d, sentence_info=%d",
            available_keys,
            len(full_text),
            len(sentence_info),
        )

        token_conf: list[float] = result.get("token_confidence", [])

        if sentence_info:
            segments = build_segments_from_sentence_info(sentence_info, token_conf)
        else:
            sentences = split_sentences(full_text)
            segments = build_segments_from_sentences(sentences, token_conf)

        log_confidence_stats(segments)
        return ASRResult(text=full_text, segments=segments)

    def _transcribe_sensevoice(
        self,
        audio_path: Path,
        sentence_timestamp: bool = False,
    ) -> ASRResult:
        """SenseVoice 模式推理 + 可选解耦说话人分离"""

        # Step 1: SenseVoice ASR - 启用时间戳输出
        results = self._model.generate(
            input=str(audio_path),
            cache={},
            language=self._sensevoice_language,
            use_itn=True,
            batch_size_s=self._batch_size,
            merge_vad=False,
            merge_length_s=_SENSEVOICE_MERGE_LENGTH_S,
            output_timestamp=True,  # 启用字级时间戳
        )

        if not results:
            return ASRResult(text="")

        # 调试：记录 SenseVoice 返回的完整结构
        if results:
            first_result = results[0] if isinstance(results, list) else results
            logger.info(
                "SenseVoice result structure - keys: %s, result type: %s",
                list(first_result.keys()) if isinstance(first_result, dict) else "not dict",
                type(first_result).__name__
            )

        # 清洗并收集所有分段
        all_segments: list[dict] = []
        all_texts: list[str] = []

        for item in results:
            raw_text = item.get("text", "")
            cleaned_text = clean_sensevoice_text(raw_text)

            if not cleaned_text.strip():
                continue

            # 噪声过滤：跳过纯语气词段落
            if self._filter_noise and is_noise_segment(cleaned_text):
                logger.debug("Filtered noise segment: %s", cleaned_text[:20])
                continue

            # 提取时间戳 - SenseVoice 返回的 timestamp 是字级时间戳列表
            timestamps = item.get("timestamp", [])

            # 调试：记录时间戳信息
            logger.debug(
                "Item keys: %s, timestamp count: %d, first 3: %s",
                list(item.keys()),
                len(timestamps) if timestamps else 0,
                timestamps[:3] if timestamps else "N/A"
            )

            if timestamps and len(timestamps) >= 1:
                # timestamps 格式: [[start, end], [start, end], ...]
                start_ms = int(timestamps[0][0])
                end_ms = int(timestamps[-1][1])
            else:
                # 没有时间戳时，尝试从音频时长估算
                start_ms = 0
                end_ms = 0
                logger.warning("No timestamps available for segment, text length: %d", len(cleaned_text))

            duration_ms = end_ms - start_ms

            # 如果 segment 过长，进行后处理分割
            if duration_ms > self._max_segment_ms and timestamps:
                sub_segments = split_long_segment(
                    cleaned_text, timestamps, self._max_segment_ms
                )
                for sub_seg in sub_segments:
                    all_segments.append(sub_seg)
                    all_texts.append(sub_seg["text"])
            else:
                all_segments.append({
                    "text": cleaned_text,
                    "start": start_ms,
                    "end": end_ms,
                })
                all_texts.append(cleaned_text)

        full_text = "".join(all_texts)

        # 调试：记录分段的时间戳范围
        if all_segments:
            time_ranges = [(s["start"], s["end"]) for s in all_segments[:5]]
            logger.info(
                "SenseVoice segments: %d, text length: %d, first 5 time ranges: %s",
                len(all_segments), len(full_text), time_ranges
            )
        else:
            logger.info("SenseVoice segments: %d, text length: %d", len(all_segments), len(full_text))

        # 如果不需要说话人分离或没有 spk_model，直接返回分段
        if not sentence_timestamp or not self._has_spk:
            segments = [
                Segment(text=s["text"], start_ms=s["start"], end_ms=s["end"])
                for s in all_segments
            ]
            return ASRResult(text=full_text, segments=segments)

        # Step 2: 解耦说话人分离
        segments = self._diarizer.diarize(self._spk_model, audio_path, all_segments)

        # 如果分离失败，回退到带时间戳的分段
        if not segments:
            segments = [
                Segment(text=s["text"], start_ms=s["start"], end_ms=s["end"])
                for s in all_segments
            ]

        return ASRResult(text=full_text, segments=segments)


    def is_loaded(self) -> bool:
        """ASR 模型权重是否在 VRAM 中。"""
        return self._model is not None

    def unload_weights(self) -> None:
        """释放 GPU 显存中的 ASR 模型权重。调用 reload() 可恢复。"""
        self._model = None
        if getattr(self, "_spk_model", None) is not None:
            self._spk_model = None
        try:
            import torch
            torch.cuda.empty_cache()
        except ImportError:
            pass
        import gc
        gc.collect()
        logger.info("ASR model weights unloaded from VRAM")

    def reload(self) -> None:
        """重新加载 ASR 模型权重（unload_weights 后恢复）。"""
        if self._model is not None:
            return
        device = self._settings.resolve_asr_device()
        if self._mode == "sensevoice":
            self._init_sensevoice_mode(self._settings, device)
        else:
            self._init_paraformer_mode(self._settings, device)
        logger.info("ASR model weights reloaded into VRAM")

