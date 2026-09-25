"""基于声纹（CAM++ embedding）聚类的说话人分离，用于 SenseVoice 模式。

流程：对每个 VAD 段按滑动窗口提取声纹 → 余弦距离层次聚类 → 每段按窗口多数票定说话人。
只有一个无时间戳的长段时，改为按窗口标签把它拆成多个说话人轮次。
"""

import logging
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from copernicus.services.asr.types import Segment

logger = logging.getLogger(__name__)

_MIN_EMB_WINDOW_MS = 500        # 声纹提取最短有效窗口（毫秒）
_MAX_SLIDING_WINDOWS = 500      # 单段最大滑动窗口数（防 OOM）
_MAX_AUDIO_DURATION_MS = 36_000_000  # 合理性上限：10 小时

# (embedding, 所属 segment 序号, 窗口起点 ms, 窗口终点 ms)
_WindowEmbedding = tuple[np.ndarray, int, int, int]


class SpeakerDiarizer:
    def __init__(
        self,
        *,
        window_ms: int,
        step_ms: int,
        threshold_ms: int,
        distance_threshold: float,
    ) -> None:
        self._window_ms = window_ms
        self._step_ms = step_ms
        self._threshold_ms = threshold_ms  # 超过此时长的段才使用滑动窗口
        self._distance_threshold = distance_threshold

    def diarize(self, spk_model, audio_path: Path, vad_segments: list[dict]) -> list[Segment]:
        """给 VAD 分段标注说话人。vad_segments 每项为 {"text", "start", "end"}；失败返回空列表。"""
        if not vad_segments:
            logger.warning("No VAD segments found for diarization")
            return []
        if not audio_path.exists():
            logger.error("Audio file does not exist: %s", audio_path)
            return []

        loaded = _load_mono_audio(audio_path)
        if loaded is None:
            return []
        speech, sample_rate, duration_ms = loaded

        # 只有一个没有有效时间戳的段：后面要用整段音频，并可能按说话人拆开
        untimed_single = len(vad_segments) == 1 and all(
            seg["start"] == 0 and seg["end"] == 0 for seg in vad_segments
        )

        logger.info(
            "Extracting speaker embeddings for %d VAD segments (window=%dms, step=%dms, threshold=%dms) ...",
            len(vad_segments), self._window_ms, self._step_ms, self._threshold_ms,
        )
        embeddings = self._collect_embeddings(
            spk_model, speech, sample_rate, duration_ms, vad_segments, untimed_single
        )
        logger.info("Extracted %d window embeddings from %d segments", len(embeddings), len(vad_segments))

        labels = self._cluster(embeddings)
        if untimed_single and len(set(labels)) > 1:
            logger.info("Splitting single segment into speaker turns based on window labels")
            return _split_by_speaker_turns(vad_segments[0], embeddings, labels)

        speakers = _vote_speakers(embeddings, labels)
        return [
            Segment(
                text=seg.get("text", ""),
                start_ms=seg["start"],
                end_ms=seg["end"],
                speaker=speakers.get(i, -1),
            )
            for i, seg in enumerate(vad_segments)
        ]

    # -- embedding extraction ------------------------------------------------

    def _collect_embeddings(
        self,
        spk_model,
        speech: np.ndarray,
        sample_rate: int,
        duration_ms: int,
        vad_segments: list[dict],
        untimed_single: bool,
    ) -> list[_WindowEmbedding]:
        collected: list[_WindowEmbedding] = []

        if untimed_single:
            step_ms = self._step_ms
            if duration_ms // step_ms > _MAX_SLIDING_WINDOWS:
                step_ms = duration_ms // _MAX_SLIDING_WINDOWS  # 动态放大步长以控制窗口数量
                logger.info("Adjusting step from %d ms to %d ms to limit windows", self._step_ms, step_ms)
            logger.warning(
                "Single segment with no timestamps detected. "
                "Using full audio for sliding window speaker diarization (%d ms, step=%d ms)",
                duration_ms, step_ms,
            )
            for emb, w_start, w_end in _sliding_window_embeddings(
                spk_model, speech, sample_rate, 0, duration_ms, self._window_ms, step_ms
            ):
                collected.append((emb, 0, w_start, w_end))
            return collected

        for seg_idx, seg in enumerate(vad_segments):
            start_ms, end_ms = seg["start"], seg["end"]
            if start_ms == 0 and end_ms == 0 and seg.get("text"):
                logger.warning("Segment %d has no valid timestamps, using full audio duration", seg_idx)
                end_ms = duration_ms

            if end_ms - start_ms > self._threshold_ms:
                for emb, w_start, w_end in _sliding_window_embeddings(
                    spk_model, speech, sample_rate, start_ms, end_ms, self._window_ms, self._step_ms
                ):
                    collected.append((emb, seg_idx, w_start, w_end))
            else:
                emb = _embed_range(spk_model, speech, sample_rate, start_ms, end_ms)
                if emb is not None:
                    collected.append((emb, seg_idx, start_ms, end_ms))
        return collected

    # -- clustering ------------------------------------------------------------

    def _cluster(self, embeddings: list[_WindowEmbedding]) -> list[int]:
        """返回每个窗口的说话人标签；少于 2 个窗口时无法聚类。"""
        if len(embeddings) >= 2:
            from sklearn.cluster import AgglomerativeClustering

            clustering = AgglomerativeClustering(
                n_clusters=None,
                distance_threshold=self._distance_threshold,
                metric="cosine",
                linkage="average",
            )
            labels = [int(x) for x in clustering.fit_predict(np.vstack([e[0] for e in embeddings]))]
            logger.info(
                "Clustered %d embeddings into %d speakers (cosine distance threshold=%.2f)",
                len(embeddings), len(set(labels)), self._distance_threshold,
            )
            return labels
        if len(embeddings) == 1:
            logger.warning("Only 1 embedding available, cannot cluster - defaulting to Speaker 1")
            return [0]
        logger.warning("No valid embeddings extracted")
        return []


def _load_mono_audio(audio_path: Path) -> tuple[np.ndarray, int, int] | None:
    """读取音频为单声道 float32，返回 (采样, 采样率, 时长 ms)；读取失败返回 None。"""
    import soundfile as sf

    logger.info("Diarization: reading audio file %s (%.2f MB)", audio_path, audio_path.stat().st_size / 1024 / 1024)
    try:
        speech, sample_rate = sf.read(str(audio_path), dtype="float32")  # 默认 float64，长音频内存翻倍
    except Exception as e:
        logger.warning("Failed to read audio for diarization: %s", e)
        return None

    if speech.ndim == 2:  # 多声道：取第一声道
        logger.warning("Audio has %d channels, using first channel", speech.shape[1])
        speech = speech[:, 0]

    duration_ms = int(len(speech) / sample_rate * 1000)
    logger.info("Audio duration: %d ms (%.1f sec)", duration_ms, duration_ms / 1000)
    if duration_ms > _MAX_AUDIO_DURATION_MS:
        logger.error(
            "Audio duration seems unreasonable (%.1f hours). Check the audio file format and ffmpeg output: %s",
            duration_ms / 3_600_000, audio_path,
        )
    return speech, sample_rate, duration_ms


def _embed_range(
    spk_model, speech: np.ndarray, sample_rate: int, start_ms: int, end_ms: int
) -> np.ndarray | None:
    """提取 [start_ms, end_ms) 这段音频的声纹；太短或模型出错时返回 None。"""
    if end_ms - start_ms < _MIN_EMB_WINDOW_MS:
        return None

    start_sample = max(0, int(start_ms / 1000 * sample_rate))
    end_sample = min(len(speech), int(end_ms / 1000 * sample_rate))
    if end_sample - start_sample < int(sample_rate * _MIN_EMB_WINDOW_MS / 1000):
        return None

    try:
        result = spk_model.generate(input=speech[start_sample:end_sample])
        if result:
            emb = result[0].get("spk_embedding")
            return np.array(emb) if emb is not None else None
    except Exception as e:
        logger.debug("Failed to extract embedding for [%d-%d]: %s", start_ms, end_ms, e)
    return None


def _sliding_window_embeddings(
    spk_model,
    speech: np.ndarray,
    sample_rate: int,
    seg_start_ms: int,
    seg_end_ms: int,
    window_ms: int,
    step_ms: int,
) -> list[tuple[np.ndarray, int, int]]:
    """在长音频段上滑动取窗提取声纹，返回 [(embedding, 窗口起点 ms, 窗口终点 ms), ...]。"""
    results: list[tuple[np.ndarray, int, int]] = []
    window_start = seg_start_ms
    while window_start < seg_end_ms:
        window_end = min(window_start + window_ms, seg_end_ms)
        if window_end - window_start < _MIN_EMB_WINDOW_MS:
            break  # 尾部不足一个有效窗口
        emb = _embed_range(spk_model, speech, sample_rate, window_start, window_end)
        if emb is not None:
            results.append((emb, window_start, window_end))
        window_start += step_ms
    return results


# -- labelling ---------------------------------------------------------------


def _vote_speakers(embeddings: list[_WindowEmbedding], labels: list[int]) -> dict[int, int]:
    """每个 segment 的说话人由其所有窗口的多数票决定。"""
    votes: dict[int, list[int]] = defaultdict(list)
    for (_, seg_idx, _, _), label in zip(embeddings, labels, strict=True):
        votes[seg_idx].append(label)
    return {seg_idx: Counter(v).most_common(1)[0][0] for seg_idx, v in votes.items()}


def _split_by_speaker_turns(
    original_seg: dict,
    embeddings: list[_WindowEmbedding],
    labels: list[int],
) -> list[Segment]:
    """把单个 segment 按窗口级说话人标签拆成多个轮次。

    VAD 只给出 1 个 segment、声纹却聚出多个说话人时使用。没有字级时间戳，文本按时长比例分配。
    """
    full_text = original_seg.get("text", "")

    def whole(speaker: int = 0) -> list[Segment]:
        return [Segment(text=full_text, start_ms=original_seg["start"], end_ms=original_seg["end"], speaker=speaker)]

    if not embeddings or len(labels) != len(embeddings):
        return whole()

    # 按时间排序后，把相邻同一说话人的窗口合并成一个轮次 (speaker, start_ms, end_ms)
    ordered = sorted(zip(embeddings, labels, strict=True), key=lambda x: x[0][2])
    turns: list[tuple[int, int, int]] = []
    speaker, start, end = ordered[0][1], ordered[0][0][2], ordered[0][0][3]
    for (_, _, w_start, w_end), label in ordered[1:]:
        if label == speaker:
            end = w_end
        else:
            turns.append((speaker, start, end))
            speaker, start, end = label, w_start, w_end
    turns.append((speaker, start, end))
    logger.info("Split into %d speaker turns from %d windows", len(turns), len(labels))

    total_duration = max(turns[-1][2] - turns[0][1], 1)  # 避免除零
    segments: list[Segment] = []
    offset = 0
    for i, (speaker, start_ms, end_ms) in enumerate(turns):
        if i == len(turns) - 1:
            text = full_text[offset:]  # 最后一个轮次拿走剩余文本
        else:
            count = int(len(full_text) * (end_ms - start_ms) / total_duration)
            text = full_text[offset:offset + count]
            offset += count
        if text.strip():
            segments.append(Segment(text=text, start_ms=start_ms, end_ms=end_ms, speaker=speaker))

    return segments or whole()
