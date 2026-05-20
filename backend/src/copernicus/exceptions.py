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


class TaskNotFoundError(CopernicusError):
    """Raised when a requested task does not exist."""


class AudioNotFoundError(CopernicusError):
    """Raised when the audio file for a task is missing."""


class ServiceNotConfiguredError(CopernicusError):
    """Raised when a required service was not initialized."""
