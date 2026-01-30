import logging
from dataclasses import dataclass, field
from pathlib import Path

from copernicus.config import Settings
from copernicus.exceptions import ASRError

logger = logging.getLogger(__name__)


@dataclass
class Segment:
    text: str
    start_ms: int = 0
    end_ms: int = 0


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
        )
        self._batch_size = settings.asr_batch_size
        logger.info("FunASR models loaded successfully.")

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

            segments: list[Segment] = []
            if "timestamp" in results[0]:
                timestamps = results[0]["timestamp"]
                sentence = results[0].get("sentence_info", [])
                for info in sentence:
                    segments.append(
                        Segment(
                            text=info.get("text", ""),
                            start_ms=info.get("start", 0),
                            end_ms=info.get("end", 0),
                        )
                    )

            return ASRResult(text=full_text, segments=segments)
        except Exception as e:
            raise ASRError(f"ASR inference failed: {e}") from e
