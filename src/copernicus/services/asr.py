import logging
from dataclasses import dataclass, field
from pathlib import Path

from copernicus.config import Settings
from copernicus.exceptions import ASRError
from copernicus.utils.text import split_sentences

logger = logging.getLogger(__name__)


@dataclass
class Segment:
    text: str
    start_ms: int = 0
    end_ms: int = 0
    confidence: float = 0.0
    speaker: int = -1


@dataclass
class ASRResult:
    text: str
    segments: list[Segment] = field(default_factory=list)


class ASRService:
    def __init__(self, settings: Settings) -> None:
        from funasr import AutoModel

        device = settings.resolve_asr_device()
        logger.info("Loading FunASR models on device=%s ...", device)

        model_kwargs: dict = {
            "model": settings.asr_model_dir,
            "device": device,
            "disable_update": True,
        }
        if settings.vad_model_dir:
            model_kwargs["vad_model"] = settings.vad_model_dir
        if settings.punc_model_dir:
            model_kwargs["punc_model"] = settings.punc_model_dir
        if settings.spk_model_dir:
            model_kwargs["spk_model"] = settings.spk_model_dir
            logger.info("Speaker diarization enabled: %s", settings.spk_model_dir)

        self._model = AutoModel(**model_kwargs)
        self._batch_size = settings.asr_batch_size
        self._has_spk = bool(settings.spk_model_dir)
        logger.info("FunASR models loaded successfully.")

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
        """Build Segment objects from FunASR sentence_info with timestamps and speaker.

        token_conf is the top-level token_confidence list from FunASR result.
        Each sentence_info item has a 'timestamp' field whose length equals the
        number of tokens in that sentence, used to slice the flat confidence array.
        """
        segments: list[Segment] = []
        conf_offset = 0

        for item in sentence_info:
            text = item.get("text", "")
            start = item.get("start", 0)
            end = item.get("end", 0)
            spk = item.get("spk", -1)

            # timestamp is a list of [start_ms, end_ms] per token
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

    def transcribe(
        self,
        audio_path: Path,
        hotwords: list[str] | None = None,
        sentence_timestamp: bool = False,
    ) -> ASRResult:
        """Run ASR inference on a WAV file. This is a blocking call.

        Args:
            sentence_timestamp: Enable sentence-level timestamps and speaker diarization.
                Requires a timestamp-capable model (e.g. paraformer-large-vad-punc or
                seaco_paraformer_large). Will be silently ignored if the model doesn't
                support it.
        """
        try:
            kwargs: dict = {
                "input": str(audio_path),
                "batch_size_s": self._batch_size,
            }
            if sentence_timestamp:
                kwargs["sentence_timestamp"] = True
            if hotwords:
                kwargs["hotword"] = " ".join(hotwords)
            if self._has_spk and sentence_timestamp:
                kwargs["return_spk_res"] = True

            results = self._model.generate(**kwargs)

            if not results:
                return ASRResult(text="")

            result = results[0]
            full_text = result.get("text", "")
            sentence_info: list[dict] = result.get("sentence_info", [])

            logger.info(
                "FunASR text length: %d, sentence_info count: %d",
                len(full_text),
                len(sentence_info),
            )

            token_conf: list[float] = result.get("token_confidence", [])

            if sentence_info:
                segments = self._build_segments_from_sentence_info(
                    sentence_info, token_conf
                )
            else:
                sentences = split_sentences(full_text)
                segments = self._build_segments_from_sentences(sentences, token_conf)

            logger.info("Split into %d segments", len(segments))

            if segments and segments[0].confidence > 0.0:
                confs = [s.confidence for s in segments]
                logger.info(
                    "Confidence stats: min=%.4f, max=%.4f, avg=%.4f, >=0.95: %d/%d",
                    min(confs),
                    max(confs),
                    sum(confs) / len(confs),
                    sum(1 for c in confs if c >= 0.95),
                    len(confs),
                )

            return ASRResult(text=full_text, segments=segments)
        except Exception as e:
            raise ASRError(f"ASR inference failed: {e}") from e
