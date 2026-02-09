import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from copernicus.config import Settings
from copernicus.exceptions import ASRError
from copernicus.utils.text import split_sentences

logger = logging.getLogger(__name__)


@dataclass
class SubSentence:
    """Original ASR sentence boundary preserved through pre-merge."""

    text: str
    start_ms: int = 0
    end_ms: int = 0


@dataclass
class Segment:
    text: str
    start_ms: int = 0
    end_ms: int = 0
    confidence: float = 0.0
    speaker: int = -1
    sub_sentences: list[SubSentence] = field(default_factory=list)


@dataclass
class ASRResult:
    text: str
    segments: list[Segment] = field(default_factory=list)


class ASRService:
    """双模式 ASR 服务：Paraformer (说话人分离) 或 SenseVoice (抗噪增强)"""

    def __init__(self, settings: Settings) -> None:
        self._mode = settings.asr_mode
        self._batch_size = settings.asr_batch_size
        device = settings.resolve_asr_device()

        # 保存配置参数供后续使用
        self._max_segment_ms = settings.sensevoice_max_segment_ms
        self._spk_window_ms = settings.spk_sliding_window_ms
        self._spk_step_ms = settings.spk_sliding_step_ms
        self._spk_threshold_ms = settings.spk_sliding_threshold_ms
        self._spk_distance_threshold = settings.spk_distance_threshold
        self._filter_noise = settings.filter_noise_segments

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
        from funasr import AutoModel

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
                "max_single_segment_time": 30000,  # 单段最长 30 秒
            }
            logger.info("  VAD model: %s (max_segment=30s)", settings.vad_model_dir)

        if settings.punc_model_dir:
            model_kwargs["punc_model"] = settings.punc_model_dir
            logger.info("  PUNC model: %s", settings.punc_model_dir)

        if settings.spk_model_dir:
            model_kwargs["spk_model"] = settings.spk_model_dir
            logger.info("  SPK model: %s", settings.spk_model_dir)

        self._model = AutoModel(**model_kwargs)
        self._has_spk = bool(settings.spk_model_dir)
        self._spk_model = None  # Paraformer 模式不需要单独的 spk_model
        logger.info("Paraformer model loaded successfully")

    def _init_sensevoice_mode(self, settings: Settings, device: str) -> None:
        """SenseVoice 解耦模式：ASR 和 SD 分离加载"""
        from funasr import AutoModel

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
                "max_single_segment_time": 15000,  # 最长 15 秒一段
            }

        if settings.asr_disable_pbar:
            asr_kwargs["disable_pbar"] = True

        self._model = AutoModel(**asr_kwargs)
        self._sensevoice_language = settings.sensevoice_language
        logger.info("SenseVoice model loaded: %s, language=%s",
                    settings.sensevoice_model_dir, self._sensevoice_language)

        # 声纹模型 (Campplus) - 用于解耦说话人分离
        if settings.spk_model_dir:
            spk_kwargs: dict = {
                "model": settings.spk_model_dir,
                "device": device,
                "disable_update": True,
            }
            if settings.asr_disable_pbar:
                spk_kwargs["disable_pbar"] = True

            self._spk_model = AutoModel(**spk_kwargs)
            self._has_spk = True
            logger.info("Speaker embedding model loaded: %s", settings.spk_model_dir)
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
        logger.info("[%s] Starting transcription: %s", self._mode.upper(), audio_path.name)
        try:
            if self._mode == "sensevoice":
                return self._transcribe_sensevoice(audio_path, sentence_timestamp)
            else:
                return self._transcribe_paraformer(audio_path, hotwords, sentence_timestamp)
        except Exception as e:
            raise ASRError(f"ASR inference failed: {e}") from e

    def _transcribe_paraformer(
        self,
        audio_path: Path,
        hotwords: list[str] | None = None,
        sentence_timestamp: bool = False,
    ) -> ASRResult:
        """Paraformer 模式推理"""
        # 说话人分离需要更小的 batch_size 以避免 OOM
        # batch_size_s 表示每批处理的音频秒数，16GB 显存建议 60-120 秒
        effective_batch_size = min(self._batch_size, 60) if self._has_spk else self._batch_size

        kwargs: dict = {
            "input": str(audio_path),
            "batch_size_s": effective_batch_size,
            "merge_vad": True,  # 开启 VAD 切分合并，避免 OOM
            "merge_length_s": 60,  # 每次合并最长 60 秒送入模型
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
            segments = self._build_segments_from_sentence_info(sentence_info, token_conf)
        else:
            sentences = split_sentences(full_text)
            segments = self._build_segments_from_sentences(sentences, token_conf)

        self._log_confidence_stats(segments)
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
            merge_vad=False,  # 关键：不合并 VAD 片段，保留每段独立时间戳
            merge_length_s=15,  # 每段最长 15 秒
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
            cleaned_text = self._clean_sensevoice_text(raw_text)

            if not cleaned_text.strip():
                continue

            # 噪声过滤：跳过纯语气词段落
            if self._filter_noise and self._is_noise_segment(cleaned_text):
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
                sub_segments = self._split_long_segment(
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
        segments = self._diarize_with_campplus(audio_path, all_segments)

        # 如果分离失败，回退到带时间戳的分段
        if not segments:
            segments = [
                Segment(text=s["text"], start_ms=s["start"], end_ms=s["end"])
                for s in all_segments
            ]

        return ASRResult(text=full_text, segments=segments)

    @staticmethod
    def _clean_sensevoice_text(text: str) -> str:
        """清洗 SenseVoice 输出的特殊标记和 emoji"""
        import re

        # 去除 SenseVoice 特殊标签 <|...|>
        text = re.sub(r"<\|[^|]+\|>", "", text)

        # 去除常见 emoji (音乐、表情等)
        emoji_pattern = re.compile(
            "["
            "\U0001F300-\U0001F9FF"  # 各类符号和表情
            "\U00002600-\U000027BF"  # 杂项符号
            "\U0001F600-\U0001F64F"  # 表情符号
            "\U0001F680-\U0001F6FF"  # 交通和地图符号
            "]+",
            flags=re.UNICODE,
        )
        text = emoji_pattern.sub("", text)

        # 去除连续重复标点
        text = re.sub(r"[。，、！？；：]{2,}", "。", text)

        # 去除孤立的标点或空白
        text = re.sub(r"^\s*[。，、！？；：]+\s*$", "", text)

        return text.strip()

    @staticmethod
    def _split_long_segment(
        text: str,
        timestamps: list[list[int]],
        max_duration_ms: int = 15000,
    ) -> list[dict]:
        """将超长 segment 基于时间戳切分为多个短段落

        Args:
            text: 完整文本
            timestamps: 字级时间戳列表 [[start, end], ...]
            max_duration_ms: 单段最大时长（毫秒）

        Returns:
            切分后的 segment 列表 [{"text", "start", "end"}, ...]
        """
        if not timestamps or len(timestamps) < 2:
            return [{"text": text, "start": 0, "end": 0}]

        # 标点符号集合（自然切分点）
        punc_chars = set("。！？；，、：.!?;,:")

        results: list[dict] = []
        current_start_idx = 0
        current_start_ms = timestamps[0][0]

        # 遍历时间戳，寻找切分点
        for i, ts in enumerate(timestamps):
            current_end_ms = ts[1]
            duration = current_end_ms - current_start_ms

            # 检查是否需要切分
            if duration >= max_duration_ms:
                # 向前搜索最近的标点符号作为切分点
                split_idx = i
                for j in range(i, current_start_idx, -1):
                    if j < len(text) and text[j] in punc_chars:
                        split_idx = j + 1
                        break

                # 如果没找到标点，就在当前位置切分
                if split_idx == i:
                    split_idx = i

                # 提取子段落
                sub_text = text[current_start_idx:split_idx].strip()
                if sub_text:
                    sub_end_ms = timestamps[min(split_idx - 1, len(timestamps) - 1)][1]
                    results.append({
                        "text": sub_text,
                        "start": int(current_start_ms),
                        "end": int(sub_end_ms),
                    })

                # 更新起始位置
                current_start_idx = split_idx
                if split_idx < len(timestamps):
                    current_start_ms = timestamps[split_idx][0]

        # 处理剩余部分
        if current_start_idx < len(text):
            remaining_text = text[current_start_idx:].strip()
            if remaining_text:
                results.append({
                    "text": remaining_text,
                    "start": int(current_start_ms),
                    "end": int(timestamps[-1][1]),
                })

        return results if results else [{"text": text, "start": int(timestamps[0][0]), "end": int(timestamps[-1][1])}]

    @staticmethod
    def _is_noise_segment(text: str) -> bool:
        """检查是否为纯噪声段落（仅包含语气词或无意义音节）

        Args:
            text: 待检查文本

        Returns:
            True 表示应该过滤
        """
        # 中文语气词和常见噪声
        noise_words_cn = {
            "嗯", "啊", "哦", "呃", "唔", "嘿", "哈", "呵",
            "噢", "喔", "诶", "哎", "唉", "呀", "吧", "呢",
            "嘛", "咯", "喽", "哇", "嗯嗯", "啊啊", "哦哦",
        }

        # 英文噪声词（ASR 幻觉常见）
        noise_words_en = {
            "the", "a", "an", "um", "uh", "yeah", "yes", "no",
            "oh", "ah", "er", "hmm", "hm", "mm", "mhm", "ok", "okay",
            "the the", "the yeah", "a a", "um um", "uh uh",
        }

        # 去除标点和空白后检查
        cleaned = text.strip().lower()
        for punc in "。，、！？；：.!?;,: ":
            cleaned = cleaned.replace(punc, " ")
        cleaned = " ".join(cleaned.split())  # 规范化空白

        # 空文本
        if not cleaned:
            return True

        # 完全匹配噪声词
        if cleaned in noise_words_cn or cleaned in noise_words_en:
            return True

        # 检查是否为重复语气词组合（如 "嗯嗯嗯"、"啊啊啊"）
        if len(cleaned) <= 6:
            unique_chars = set(cleaned.replace(" ", ""))
            if len(unique_chars) <= 2 and all(c in noise_words_cn for c in unique_chars):
                return True

        # 检查是否仅由英文噪声词组成
        words = cleaned.split()
        if words and all(w in noise_words_en for w in words):
            return True

        return False

    def _diarize_with_campplus(
        self, audio_path: Path, vad_segments: list[dict]
    ) -> list[Segment]:
        """基于滑动窗口声纹聚类的说话人分离

        Args:
            audio_path: 音频文件路径
            vad_segments: VAD 分段列表，每项包含 {"text", "start", "end"}

        核心逻辑：
        1. 对长 segment 使用滑动窗口提取多个声纹 embedding
        2. 基于余弦距离聚类（声纹相似度）
        3. 多数投票决定每个 segment 的说话人
        """
        import soundfile as sf
        from collections import Counter, defaultdict
        from sklearn.cluster import AgglomerativeClustering

        if not vad_segments:
            logger.warning("No VAD segments found for diarization")
            return []

        # 验证音频文件
        logger.info("Diarization: reading audio file %s", audio_path)
        if audio_path.exists():
            file_size = audio_path.stat().st_size
            logger.info("Audio file size: %d bytes (%.2f MB)", file_size, file_size / 1024 / 1024)
        else:
            logger.error("Audio file does not exist: %s", audio_path)
            return []

        try:
            speech, sample_rate = sf.read(str(audio_path))
        except Exception as e:
            logger.warning("Failed to read audio for diarization: %s", e)
            return []

        # 滑动窗口参数（来自配置）
        window_ms = self._spk_window_ms
        step_ms = self._spk_step_ms
        min_window_ms = 500    # 最短有效窗口 0.5 秒
        threshold_ms = self._spk_threshold_ms
        distance_threshold = self._spk_distance_threshold

        logger.info(
            "Extracting speaker embeddings for %d VAD segments "
            "(window=%dms, step=%dms, threshold=%dms) ...",
            len(vad_segments), window_ms, step_ms, threshold_ms
        )

        # 收集所有窗口的 embedding: (embedding, seg_idx, window_start_ms, window_end_ms)
        all_window_embeddings: list[tuple[np.ndarray, int, int, int]] = []

        # 获取音频总时长（毫秒），用于处理没有时间戳的情况
        # soundfile.read() 返回 (frames, channels) 或 (frames,) 的 numpy 数组
        # speech.shape[0] 始终是帧数（样本数）
        logger.info(
            "Audio loaded: shape=%s, dtype=%s, sample_rate=%d, ndim=%d",
            speech.shape, speech.dtype, sample_rate, speech.ndim
        )

        # 确保单声道
        if speech.ndim == 2:
            # 多声道音频，取第一声道
            logger.warning("Audio has %d channels, using first channel", speech.shape[1])
            speech = speech[:, 0]

        n_frames = len(speech)
        audio_duration_ms = int(n_frames / sample_rate * 1000)
        logger.info("Audio duration: %d frames / %d Hz = %d ms (%.1f sec)",
                    n_frames, sample_rate, audio_duration_ms, audio_duration_ms / 1000)

        # 合理性检查：音频时长不应超过 10 小时
        if audio_duration_ms > 36000000:
            logger.error(
                "Audio duration seems unreasonable (%d ms = %.1f hours). "
                "Check: 1) audio file format 2) ffmpeg output 3) soundfile parsing. "
                "File: %s, size: %d bytes",
                audio_duration_ms, audio_duration_ms / 3600000,
                audio_path, audio_path.stat().st_size if audio_path.exists() else -1
            )

        # 检查是否所有 segment 都没有有效时间戳
        all_invalid_timestamps = all(
            seg["start"] == 0 and seg["end"] == 0
            for seg in vad_segments
        )

        if all_invalid_timestamps and len(vad_segments) == 1:
            # 特殊情况：只有 1 个 segment 且没有时间戳
            # 直接对整个音频使用滑动窗口提取 embedding

            # 计算预期窗口数量，如果太多则增大步长
            expected_windows = audio_duration_ms // step_ms
            max_windows = 500  # 最多提取 500 个窗口以避免 OOM

            effective_step_ms = step_ms
            if expected_windows > max_windows:
                # 动态调整步长以控制窗口数量
                effective_step_ms = audio_duration_ms // max_windows
                logger.info(
                    "Adjusting step from %d ms to %d ms to limit windows (%d -> %d)",
                    step_ms, effective_step_ms, expected_windows, max_windows
                )

            logger.warning(
                "Single segment with no timestamps detected. "
                "Using full audio for sliding window speaker diarization (%d ms, step=%d ms)",
                audio_duration_ms, effective_step_ms
            )
            window_embs = self._extract_sliding_window_embeddings(
                speech, sample_rate,
                0, audio_duration_ms,
                window_ms, effective_step_ms, min_window_ms
            )
            # 所有窗口都属于 segment 0
            for emb, w_start, w_end in window_embs:
                all_window_embeddings.append((emb, 0, w_start, w_end))
        else:
            # 正常情况：遍历每个 segment
            for seg_idx, seg in enumerate(vad_segments):
                seg_start_ms = seg["start"]
                seg_end_ms = seg["end"]
                duration_ms = seg_end_ms - seg_start_ms

                # 如果时间戳无效（都是 0），使用整个音频时长
                if seg_start_ms == 0 and seg_end_ms == 0 and len(seg.get("text", "")) > 0:
                    logger.warning(
                        "Segment %d has no valid timestamps, using full audio duration (%d ms)",
                        seg_idx, audio_duration_ms
                    )
                    seg_start_ms = 0
                    seg_end_ms = audio_duration_ms
                    duration_ms = audio_duration_ms

                logger.debug(
                    "Segment %d: start=%d, end=%d, duration=%d ms",
                    seg_idx, seg_start_ms, seg_end_ms, duration_ms
                )

                if duration_ms > threshold_ms:
                    # 长 segment：使用滑动窗口提取多个 embedding
                    window_embs = self._extract_sliding_window_embeddings(
                        speech, sample_rate,
                        seg_start_ms, seg_end_ms,
                        window_ms, step_ms, min_window_ms
                    )
                    for emb, w_start, w_end in window_embs:
                        all_window_embeddings.append((emb, seg_idx, w_start, w_end))
                else:
                    # 短 segment：单一 embedding
                    emb = self._extract_single_embedding(
                        speech, sample_rate, seg_start_ms, seg_end_ms, min_window_ms
                    )
                    if emb is not None:
                        all_window_embeddings.append((emb, seg_idx, seg_start_ms, seg_end_ms))

        logger.info("Extracted %d window embeddings from %d segments",
                    len(all_window_embeddings), len(vad_segments))

        # 聚类
        window_labels: list[int] = []
        if len(all_window_embeddings) >= 2:
            X = np.vstack([e[0] for e in all_window_embeddings])
            clustering = AgglomerativeClustering(
                n_clusters=None,
                distance_threshold=distance_threshold,
                metric="cosine",
                linkage="average",
            )
            window_labels = list(clustering.fit_predict(X))
            n_speakers = len(set(window_labels))
            logger.info("Clustered %d embeddings into %d speakers (cosine distance threshold=%.2f)",
                        len(all_window_embeddings), n_speakers, distance_threshold)

            # 多数投票：每个 segment 的说话人由其所有窗口的投票决定
            segment_votes: dict[int, list[int]] = defaultdict(list)
            for i, (_, seg_idx, _, _) in enumerate(all_window_embeddings):
                segment_votes[seg_idx].append(int(window_labels[i]))

            segment_speakers: dict[int, int] = {}
            for seg_idx, votes in segment_votes.items():
                segment_speakers[seg_idx] = Counter(votes).most_common(1)[0][0]
        elif len(all_window_embeddings) == 1:
            # 只有 1 个 embedding，无法聚类
            logger.warning("Only 1 embedding available, cannot cluster - defaulting to Speaker 1")
            window_labels = [0]
            segment_speakers = {all_window_embeddings[0][1]: 0}
        else:
            # 没有有效 embedding
            logger.warning("No valid embeddings extracted")
            segment_speakers = {}

        # 特殊处理：当只有 1 个 VAD segment 但检测到多个说话人时，
        # 尝试基于窗口时间戳拆分为多个 segment
        if (all_invalid_timestamps and len(vad_segments) == 1 and
                len(set(window_labels)) > 1 and len(all_window_embeddings) > 1):
            logger.info("Splitting single segment into speaker turns based on window labels")
            segments = self._split_by_speaker_turns(
                vad_segments[0], all_window_embeddings, window_labels
            )
        else:
            # 构建 Segment 列表
            segments: list[Segment] = []
            for i, seg in enumerate(vad_segments):
                spk = segment_speakers.get(i, -1)
                segments.append(Segment(
                    text=seg.get("text", ""),
                    start_ms=seg["start"],
                    end_ms=seg["end"],
                    speaker=spk,
                ))

        return segments

    def _split_by_speaker_turns(
        self,
        original_seg: dict,
        window_embeddings: list[tuple[np.ndarray, int, int, int]],
        labels: list[int],
    ) -> list[Segment]:
        """基于窗口级说话人标签拆分单个 segment 为多个说话人轮次

        当 VAD 只返回 1 个 segment 但声纹聚类检测到多个说话人时使用。
        由于没有字级时间戳，文本按比例分配到各个说话人轮次。

        Args:
            original_seg: 原始 segment {"text", "start", "end"}
            window_embeddings: 窗口 embedding 列表 [(emb, seg_idx, start_ms, end_ms), ...]
            labels: 每个窗口的说话人标签

        Returns:
            拆分后的 Segment 列表
        """
        if not window_embeddings or len(labels) != len(window_embeddings):
            return [Segment(
                text=original_seg.get("text", ""),
                start_ms=original_seg["start"],
                end_ms=original_seg["end"],
                speaker=0,
            )]

        # 按时间顺序排序窗口
        sorted_windows = sorted(
            zip(window_embeddings, labels),
            key=lambda x: x[0][2]  # 按 window_start_ms 排序
        )

        # 合并相邻相同说话人的窗口为一个"轮次"
        turns: list[tuple[int, int, int]] = []  # (speaker, start_ms, end_ms)
        current_speaker = sorted_windows[0][1]
        current_start = sorted_windows[0][0][2]
        current_end = sorted_windows[0][0][3]

        for (_, _, w_start, w_end), speaker in sorted_windows[1:]:
            if speaker == current_speaker:
                current_end = w_end
            else:
                turns.append((current_speaker, current_start, current_end))
                current_speaker = speaker
                current_start = w_start
                current_end = w_end

        turns.append((current_speaker, current_start, current_end))

        logger.info("Split into %d speaker turns from %d windows", len(turns), len(labels))

        # 计算音频总时长
        total_duration = turns[-1][2] - turns[0][1]
        if total_duration <= 0:
            total_duration = 1  # 避免除零

        # 按时间比例分配文本
        full_text = original_seg.get("text", "")
        text_len = len(full_text)

        segments: list[Segment] = []
        text_offset = 0

        for i, (speaker, start_ms, end_ms) in enumerate(turns):
            turn_duration = end_ms - start_ms
            # 计算该轮次应分配的字符数
            if i == len(turns) - 1:
                # 最后一个轮次：分配剩余所有文本
                turn_text = full_text[text_offset:]
            else:
                char_count = int(text_len * turn_duration / total_duration)
                turn_text = full_text[text_offset:text_offset + char_count]
                text_offset += char_count

            if turn_text.strip():
                segments.append(Segment(
                    text=turn_text,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    speaker=speaker,
                ))

        if not segments:
            # 如果没有有效分段，返回原始 segment
            segments = [Segment(
                text=full_text,
                start_ms=original_seg["start"],
                end_ms=original_seg["end"],
                speaker=0,
            )]

        return segments

    def _extract_sliding_window_embeddings(
        self,
        speech: np.ndarray,
        sample_rate: int,
        seg_start_ms: int,
        seg_end_ms: int,
        window_ms: int = 1500,
        step_ms: int = 750,
        min_window_ms: int = 500,
    ) -> list[tuple[np.ndarray, int, int]]:
        """从长音频段中使用滑动窗口提取多个声纹 embedding

        Args:
            speech: 完整音频数据
            sample_rate: 采样率
            seg_start_ms: 段落起始时间（毫秒）
            seg_end_ms: 段落结束时间（毫秒）
            window_ms: 窗口大小（毫秒）
            step_ms: 滑动步长（毫秒）
            min_window_ms: 最小有效窗口（毫秒）

        Returns:
            [(embedding, window_start_ms, window_end_ms), ...]
        """
        results: list[tuple[np.ndarray, int, int]] = []
        min_samples = int(sample_rate * min_window_ms / 1000)

        window_start = seg_start_ms
        while window_start < seg_end_ms:
            window_end = min(window_start + window_ms, seg_end_ms)

            # 检查窗口是否足够长
            if window_end - window_start < min_window_ms:
                break

            # 提取音频切片
            start_sample = int(window_start / 1000 * sample_rate)
            end_sample = int(window_end / 1000 * sample_rate)
            n_frames = speech.shape[0] if speech.ndim >= 1 else len(speech)
            start_sample = max(0, start_sample)
            end_sample = min(n_frames, end_sample)

            if end_sample - start_sample < min_samples:
                window_start += step_ms
                continue

            sub_audio = speech[start_sample:end_sample]

            try:
                emb_result = self._spk_model.generate(input=sub_audio)
                if emb_result and len(emb_result) > 0:
                    emb = emb_result[0].get("spk_embedding")
                    if emb is not None:
                        results.append((np.array(emb), window_start, window_end))
            except Exception as e:
                logger.debug("Failed to extract embedding for window [%d-%d]: %s",
                            window_start, window_end, e)

            window_start += step_ms

        return results

    def _extract_single_embedding(
        self,
        speech: np.ndarray,
        sample_rate: int,
        start_ms: int,
        end_ms: int,
        min_window_ms: int = 500,
    ) -> np.ndarray | None:
        """从单个短音频段提取声纹 embedding

        Args:
            speech: 完整音频数据
            sample_rate: 采样率
            start_ms: 起始时间（毫秒）
            end_ms: 结束时间（毫秒）
            min_window_ms: 最小有效时长（毫秒）

        Returns:
            声纹 embedding 或 None
        """
        duration_ms = end_ms - start_ms
        if duration_ms < min_window_ms:
            return None

        start_sample = int(start_ms / 1000 * sample_rate)
        end_sample = int(end_ms / 1000 * sample_rate)
        n_frames = speech.shape[0] if speech.ndim >= 1 else len(speech)
        start_sample = max(0, start_sample)
        end_sample = min(n_frames, end_sample)

        min_samples = int(sample_rate * min_window_ms / 1000)
        if end_sample - start_sample < min_samples:
            return None

        sub_audio = speech[start_sample:end_sample]

        try:
            emb_result = self._spk_model.generate(input=sub_audio)
            if emb_result and len(emb_result) > 0:
                emb = emb_result[0].get("spk_embedding")
                return np.array(emb) if emb is not None else None
        except Exception as e:
            logger.debug("Failed to extract embedding for segment [%d-%d]: %s",
                        start_ms, end_ms, e)
        return None

    @staticmethod
    def _build_segments_from_sentences(
        sentences: list[str], token_conf: list[float]
    ) -> list[Segment]:
        """Build Segment objects from plain sentences (fallback path)."""
        if not token_conf:
            return [Segment(text=s) for s in sentences]

        punc_chars = set("。！？；，、：\u201c\u201d\u2018\u2019（）《》【】…—·\n.!?;,:\"'()[]")
        segments: list[Segment] = []
        conf_idx = 0

        for sent in sentences:
            scores: list[float] = []
            for ch in sent:
                if ch in punc_chars:
                    continue
                if conf_idx < len(token_conf):
                    scores.append(token_conf[conf_idx])
                    conf_idx += 1
            avg_conf = sum(scores) / len(scores) if scores else 0.0
            segments.append(Segment(text=sent, confidence=avg_conf))

        return segments

    @staticmethod
    def _build_segments_from_sentence_info(
        sentence_info: list[dict],
        token_conf: list[float],
    ) -> list[Segment]:
        """Build Segment objects from FunASR sentence_info with timestamps and speaker."""
        segments: list[Segment] = []
        conf_offset = 0

        for item in sentence_info:
            text = item.get("text", "")
            start = item.get("start", 0)
            end = item.get("end", 0)
            spk = item.get("spk", -1)

            timestamps = item.get("timestamp", [])
            n_tokens = len(timestamps)

            if token_conf and n_tokens > 0 and conf_offset < len(token_conf):
                chunk = token_conf[conf_offset : conf_offset + n_tokens]
                avg_conf = sum(chunk) / len(chunk) if chunk else 0.0
                conf_offset += n_tokens
            else:
                avg_conf = 0.0

            segments.append(
                Segment(
                    text=text,
                    start_ms=start,
                    end_ms=end,
                    confidence=avg_conf,
                    speaker=spk,
                )
            )
        return segments

    @staticmethod
    def _log_confidence_stats(segments: list[Segment]) -> None:
        """Log confidence statistics for segments."""
        if not segments or segments[0].confidence == 0.0:
            return

        confs = [s.confidence for s in segments]
        logger.info(
            "Confidence stats: min=%.4f, max=%.4f, avg=%.4f, >=0.95: %d/%d",
            min(confs),
            max(confs),
            sum(confs) / len(confs),
            sum(1 for c in confs if c >= 0.95),
            len(confs),
        )
