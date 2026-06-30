"""Abstract baseline interface — drop-in alternatives to ``VLMTaskPlanner``."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List

import numpy as np


class BaseBaseline(ABC):
    """One-shot baseline planner with the same signature as ``VLMTaskPlanner.plan``.

    Baselines deliberately do NOT receive STM or LTM — that's what makes them
    baselines. The evaluator uses them to produce the CaP-V / COME comparison
    rows in Tables II and III.
    """

    @abstractmethod
    def plan(
        self,
        instruction: str,
        image: np.ndarray,
        available_skills: List[str],
    ) -> Dict[str, Any]:
        """Return ``{"skill": ..., "parameters": ..., "reasoning": ...}``."""

    @abstractmethod
    def reset(self) -> None:
        """Reset any internal state between trials (mostly a no-op for stateless baselines)."""

    @property
    @abstractmethod
    def baseline_name(self) -> str:
        """Short identifier used in CSV / logs (e.g., ``"cap_v"``)."""
