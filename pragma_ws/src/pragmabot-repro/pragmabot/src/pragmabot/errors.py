"""PragmaBot-wide exception types."""

from __future__ import annotations


class PragmaBotError(RuntimeError):
    """Base class for PragmaBot runtime errors."""


class VLMError(PragmaBotError):
    """Any VLM-side failure (transport, API, response shape)."""


class VLMOutputParseError(VLMError):
    """Raised when a VLM response cannot be parsed as the expected JSON."""

    def __init__(self, message: str, raw: str = "") -> None:
        super().__init__(message)
        self.raw = raw


class PerceptionError(PragmaBotError):
    """Raised when the perception backend fails (model, segmentation, etc.)."""


class PlanningError(PragmaBotError):
    """Raised when the task planner cannot produce a usable action."""


class ExecutionError(PragmaBotError):
    """Raised when the robot backend fails to execute a planned action."""


class PragmaBotMemoryError(PragmaBotError):
    """Raised when an LTM/STM operation fails (load, save, retrieve)."""


# Backwards-compatible alias — the spec refers to this as ``MemoryError``,
# but that shadows the built-in. Expose both names.
MemoryError = PragmaBotMemoryError
