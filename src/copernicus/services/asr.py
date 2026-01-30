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


@dataclass
class ASRResult:
    text: str
    segments: list[Segment] = field(default_factory=list)


class ASRService:
    def __init__(self, settings: Settings) -> None:
        from funasr import AutoModel

        device = settings.resolve_asr_device()
        logger.info("Loading FunASR models on device=%s ...", device)

        self._model = AutoModel(
            model=settings.asr_model_dir,
            vad_model=settings.vad_model_dir,
            punc_model=settings.punc_model_dir,
            device=device,
            disable_update=True,
        )
        self._batch_size = settings.asr_batch_size
        logger.info("FunASR models loaded successfully.")

    @staticmethod
    def _build_segments(
        sentences: list[str], token_conf: list[float]
    ) -> list[Segment]:
        """Build Segment objects from sentences with optional confidence data."""
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

    def transcribe(
        self, audio_path: Path, hotwords: list[str] | None = None
    ) -> ASRResult:
        """Run ASR inference on a WAV file. This is a blocking call."""
        try:
            kwargs: dict = {
                "input": str(audio_path),
                "batch_size_s": self._batch_size,
            }
            if hotwords:
                kwargs["hotword"] = " ".join(hotwords)

            results = self._model.generate(**kwargs)

            if not results:
                return ASRResult(text="")

            full_text = results[0].get("text", "")
            token_conf: list[float] = results[0].get("token_confidence", [])

            logger.info(
                "FunASR text length: %d, token_confidence length: %d",
                len(full_text),
                len(token_conf),
            )

            sentences = split_sentences(full_text)
            segments = self._build_segments(sentences, token_conf)

            logger.info("Split into %d sentences", len(segments))

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
