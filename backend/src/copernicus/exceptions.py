class CopernicusError(Exception):
    """Base exception for Copernicus service."""


class AudioProcessingError(CopernicusError):
    """Raised when audio preprocessing fails (e.g. ffmpeg error)."""


class ASRError(CopernicusError):
    """Raised when ASR inference fails."""


class ComplianceError(CopernicusError):
    """Raised when compliance audit fails."""


class TaskNotFoundError(CopernicusError):
    """Raised when a requested task does not exist."""


class AudioNotFoundError(CopernicusError):
    """Raised when the audio file for a task is missing."""


class ServiceNotConfiguredError(CopernicusError):
    """Raised when a required service was not initialized."""


class InvalidIdentifierError(CopernicusError, ValueError):
    """Raised when a client-supplied identifier (task_id / file_hash) has an illegal format."""


class TaskBusyError(CopernicusError):
    """Raised when an operation requires a task that is currently running."""


class QueueFullError(CopernicusError):
    """Raised when too many media tasks are already queued or running."""
