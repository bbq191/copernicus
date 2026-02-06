import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from copernicus.services.asr import ASRResult, Segment
from copernicus.services.audio import AudioService
from copernicus.services.asr import ASRService
from copernicus.services.corrector import CorrectorService, ProgressCallback
from copernicus.utils.text import (
    format_timestamp,
    group_segments,
    merge_transcript_entries,
    pre_merge_segments,
    smooth_speakers,
)

logger = logging.getLogger(__name__)


@dataclass
class TranscriptionResult:
    raw_text: str
    corrected_text: str
    segments: list[Segment] = field(default_factory=list)
    processing_time_ms: float = 0.0


@dataclass
class TranscriptEntry:
    timestamp: str
    timestamp_ms: int
    speaker: str
    text: str
    text_corrected: str


@dataclass
class TranscriptResult:
    transcript: list[TranscriptEntry] = field(default_factory=list)
    processing_time_ms: float = 0.0


def _load_hotwords_file(path: Path | None) -> list[str]:
    """Load hotwords from a text file (one word per line, # for comments)."""
    if path is None:
        return []
    if not path.exists():
        logger.warning("Hotwords file not found: %s", path)
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    words = [line.strip() for line in lines if line.strip() and not line.startswith("#")]
    logger.info("Loaded %d hotwords from %s", len(words), path)
    return words


class PipelineService:
    def __init__(
        self,
        audio_service: AudioService,
        asr_service: ASRService,
        corrector_service: CorrectorService,
        confidence_threshold: float = 0.95,
        chunk_size: int = 800,
        run_merge_gap: int = 3,
        pre_merge_gap_ms: int = 1000,
        hotwords_file: Path | None = None,
    ) -> None:
        self._audio = audio_service
        self._asr = asr_service
        self._corrector = corrector_service
        self._confidence_threshold = confidence_threshold
        self._chunk_size = chunk_size
        self._run_merge_gap = run_merge_gap
        self._pre_merge_gap_ms = pre_merge_gap_ms
        self._global_hotwords = _load_hotwords_file(hotwords_file)
        self._asr_lock = asyncio.Lock()

    def _merge_hotwords(self, request_hotwords: list[str] | None) -> list[str] | None:
        """Combine global hotwords with per-request hotwords."""
        combined = list(self._global_hotwords)
        if request_hotwords:
            combined.extend(request_hotwords)
        return combined if combined else None

    # ------------------------------------------------------------------ #
    #  Original pipeline (plain text mode)
    # ------------------------------------------------------------------ #

    async def process(
        self,
        audio_bytes: bytes,
        filename: str,
        hotwords: list[str] | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> TranscriptionResult:
        """Run the full pipeline: preprocess -> ASR -> confidence filter -> LLM correction."""
        start = time.perf_counter()

        merged_hw = self._merge_hotwords(hotwords)
        wav_path: Path = await self._audio.preprocess(audio_bytes, filename)

        try:
            async with self._asr_lock:
                asr_result: ASRResult = await asyncio.to_thread(
                    self._asr.transcribe, wav_path, merged_hw
                )
            corrected_text = await self._correct_segments(asr_result, on_progress)
        finally:
            self._audio.cleanup(wav_path)

        elapsed_ms = (time.perf_counter() - start) * 1000

        return TranscriptionResult(
            raw_text=asr_result.text,
            corrected_text=corrected_text,
            segments=asr_result.segments,
            processing_time_ms=round(elapsed_ms, 2),
        )

    async def _correct_segments(
        self,
        asr_result: ASRResult,
        on_progress: ProgressCallback | None = None,
    ) -> str:
        """Apply confidence-based filtering and correct only low-confidence segments."""
        if not asr_result.segments:
            return await self._corrector.correct(asr_result.text, on_progress=on_progress)

        segments = asr_result.segments
        has_confidence = any(seg.confidence > 0.0 for seg in segments)

        if has_confidence:
            skipped = sum(
                1 for seg in segments if seg.confidence >= self._confidence_threshold
            )
            logger.info(
                "Confidence filter: %d/%d segments above threshold (%.2f), skipping LLM",
                skipped,
                len(segments),
                self._confidence_threshold,
            )
            if skipped == len(segments):
                return asr_result.text
            needs_correction = [
                seg.confidence < self._confidence_threshold for seg in segments
            ]
        else:
            needs_correction = [True] * len(segments)

        # Group consecutive low-confidence segments into runs
        raw_runs: list[list[int]] = []
        current_run: list[int] = []
        for i, nc in enumerate(needs_correction):
            if nc:
                current_run.append(i)
            else:
                if current_run:
                    raw_runs.append(current_run)
                    current_run = []
        if current_run:
            raw_runs.append(current_run)

        # Merge adjacent runs separated by small gaps
        merged_runs: list[list[int]] = []
        for run in raw_runs:
            if merged_runs and run[0] - merged_runs[-1][-1] - 1 <= self._run_merge_gap:
                gap_indices = list(range(merged_runs[-1][-1] + 1, run[0]))
                merged_runs[-1].extend(gap_indices + run)
            else:
                merged_runs.append(list(run))

        if len(merged_runs) < len(raw_runs):
            logger.info(
                "Run merge: %d -> %d runs (gap <= %d)",
                len(raw_runs),
                len(merged_runs),
                self._run_merge_gap,
            )

        # Build text chunks from merged runs
        correction_tasks: list[tuple[list[int], str]] = []
        for run in merged_runs:
            run_segs = [segments[i] for i in run]
            groups = group_segments(run_segs, self._chunk_size)
            offset = 0
            for group in groups:
                indices = run[offset : offset + len(group)]
                text = "".join(seg.text for seg in group)
                correction_tasks.append((indices, text))
                offset += len(group)

        logger.info(
            "Correcting %d/%d segments in %d chunks",
            sum(len(idx) for idx, _ in correction_tasks),
            len(segments),
            len(correction_tasks),
        )

        texts_to_correct = [text for _, text in correction_tasks]
        corrected = await self._corrector.correct_segments(
            texts_to_correct, on_progress=on_progress
        )

        # Map corrected text back to segment indices
        corrected_map: dict[int, str | None] = {}
        for (indices, _), corrected_text in zip(correction_tasks, corrected):
            corrected_map[indices[0]] = corrected_text
            for idx in indices[1:]:
                corrected_map[idx] = None

        # Reassemble full text
        result_parts: list[str] = []
        for i, seg in enumerate(segments):
            if i in corrected_map:
                if corrected_map[i] is not None:
                    result_parts.append(corrected_map[i])  # type: ignore[arg-type]
            else:
                result_parts.append(seg.text)

        return "".join(result_parts)

    async def process_raw(
        self,
        audio_bytes: bytes,
        filename: str,
        hotwords: list[str] | None = None,
    ) -> TranscriptionResult:
        """Run ASR only, without LLM correction."""
        start = time.perf_counter()

        merged_hw = self._merge_hotwords(hotwords)
        wav_path: Path = await self._audio.preprocess(audio_bytes, filename)

        try:
            async with self._asr_lock:
                asr_result: ASRResult = await asyncio.to_thread(
                    self._asr.transcribe, wav_path, merged_hw
                )
        finally:
            self._audio.cleanup(wav_path)

        elapsed_ms = (time.perf_counter() - start) * 1000

        return TranscriptionResult(
            raw_text=asr_result.text,
            corrected_text=asr_result.text,
            segments=asr_result.segments,
            processing_time_ms=round(elapsed_ms, 2),
        )

    # ------------------------------------------------------------------ #
    #  Transcript pipeline (speaker + timestamp mode)
    # ------------------------------------------------------------------ #

    async def process_transcript(
        self,
        audio_bytes: bytes,
        filename: str,
        hotwords: list[str] | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> TranscriptResult:
        """Run transcript pipeline: ASR (with timestamps) -> JSON-to-JSON LLM correction."""
        logger.info("Pipeline process_transcript started for: %s", filename)
        start = time.perf_counter()

        merged_hw = self._merge_hotwords(hotwords)
        logger.info("Audio preprocessing starting...")
        wav_path: Path = await self._audio.preprocess(audio_bytes, filename)
        logger.info("Audio preprocessed to: %s", wav_path)

        try:
            logger.info("Starting ASR transcription (sentence_timestamp=True)...")
            async with self._asr_lock:
                asr_result: ASRResult = await asyncio.to_thread(
                    self._asr.transcribe, wav_path, merged_hw, True
                )
            logger.info(
                "ASR completed: %d segments, %d chars, speakers: %s",
                len(asr_result.segments),
                len(asr_result.text),
                sorted(set(s.speaker for s in asr_result.segments)) if asr_result.segments else "N/A",
            )
        finally:
            self._audio.cleanup(wav_path)

        segments = asr_result.segments
        if not segments:
            elapsed_ms = (time.perf_counter() - start) * 1000
            return TranscriptResult(processing_time_ms=round(elapsed_ms, 2))

        # Step 1: Smooth speaker diarization flicker before correction
        smooth_speakers(segments)

        # Step 2: Pre-merge fine-grained segments to reduce LLM batch count
        raw_count = len(segments)
        segments = pre_merge_segments(segments, gap_ms=self._pre_merge_gap_ms)
        logger.info(
            "ASR pre-merge: %d -> %d segments",
            raw_count,
            len(segments),
        )

        correction_map = await self._correct_transcript_segments(
            segments, on_progress
        )

        # Step 3: Build raw entries (skip noise-filtered segments)
        raw_entries: list[dict] = []
        noise_filtered = 0
        for i, seg in enumerate(segments):
            corrected = correction_map.get(i, seg.text)
            # 跳过被阶段 1 过滤的纯噪声段落（空字符串）
            if corrected == "":
                noise_filtered += 1
                continue
            speaker_label = f"Speaker {seg.speaker + 1}" if seg.speaker >= 0 else "Speaker 1"
            raw_entries.append({
                "timestamp": format_timestamp(seg.start_ms),
                "timestamp_ms": seg.start_ms,
                "speaker": speaker_label,
                "text": seg.text,
                "text_corrected": corrected,
            })

        if noise_filtered > 0:
            logger.info("Noise filtered: %d segments removed", noise_filtered)

        # Step 4: Merge consecutive entries from the same speaker
        merged_entries = merge_transcript_entries(raw_entries, gap_threshold_ms=5000)

        logger.info(
            "Transcript merge: %d -> %d entries",
            len(raw_entries),
            len(merged_entries),
        )

        transcript: list[TranscriptEntry] = [
            TranscriptEntry(
                timestamp=e["timestamp"],
                timestamp_ms=e["timestamp_ms"],
                speaker=e["speaker"],
                text=e["text"],
                text_corrected=e["text_corrected"],
            )
            for e in merged_entries
        ]

        elapsed_ms = (time.perf_counter() - start) * 1000

        return TranscriptResult(
            transcript=transcript,
            processing_time_ms=round(elapsed_ms, 2),
        )

    async def _correct_transcript_segments(
        self,
        segments: list[Segment],
        on_progress: ProgressCallback | None = None,
    ) -> dict[int, str]:
        """Apply confidence-based filtering and correct via JSON-to-JSON approach."""
        has_confidence = any(seg.confidence > 0.0 for seg in segments)

        if has_confidence:
            skipped = sum(
                1 for seg in segments if seg.confidence >= self._confidence_threshold
            )
            logger.info(
                "Transcript confidence filter: %d/%d above threshold (%.2f)",
                skipped,
                len(segments),
                self._confidence_threshold,
            )
            if skipped == len(segments):
                return {i: seg.text for i, seg in enumerate(segments)}
            needs_correction = [
                seg.confidence < self._confidence_threshold for seg in segments
            ]
        else:
            needs_correction = [True] * len(segments)

        entries: list[dict] = []
        for i, seg in enumerate(segments):
            if needs_correction[i]:
                entries.append({"id": i, "text": seg.text})

        if not entries:
            return {i: seg.text for i, seg in enumerate(segments)}

        logger.info(
            "Transcript: correcting %d/%d segments via JSON-to-JSON",
            len(entries),
            len(segments),
        )

        correction_map = await self._corrector.correct_transcript(
            entries, on_progress=on_progress
        )

        result: dict[int, str] = {}
        for i, seg in enumerate(segments):
            result[i] = correction_map.get(i, seg.text)

        return result
