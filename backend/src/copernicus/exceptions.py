class CopernicusError(Exception):
    """Base exception for Copernicus service."""


class AudioProcessingError(CopernicusError):
    """Raised when audio preprocessing fails (e.g. ffmpeg error)."""


class ASRError(CopernicusError):
    """Raised when ASR inference fails."""


class CorrectionError(CopernicusError):
    """Raised when LLM text correction fails."""


class ComplianceError(CopernicusError):
    """Raised when compliance audit fails."""
