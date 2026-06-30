"""Condition manager — temporarily override pipeline knobs per evaluation cell."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Dict, Iterator

if TYPE_CHECKING:  # pragma: no cover
    from ..pipeline import PragmaBot


CONDITIONS: Dict[str, Dict[str, object]] = {
    "cap_v": {
        "use_stm": False,
        "use_ltm": False,
        "description": "CaP-V: VLM with visual feedback, no memory",
    },
    "come": {
        "use_stm": False,
        "use_ltm": False,
        "description": "COME: closed-loop VLM, no memory",
    },
    "pragmabot_stm_only": {
        "use_stm": True,
        "use_ltm": False,
        "description": "PragmaBot with STM only (no LTM/RAG)",
    },
    "pragmabot": {
        "use_stm": True,
        "use_ltm": True,
        "description": "PragmaBot with STM + LTM/RAG (full system)",
    },
}


class ConditionManager:
    """Apply / restore pipeline flags for an evaluation condition."""

    def __init__(self, conditions: Dict[str, Dict[str, object]] = None) -> None:
        self._conditions = dict(conditions or CONDITIONS)

    # ------------------------------------------------------------------

    def get_condition_description(self, condition: str) -> str:
        cfg = self._conditions.get(condition)
        if cfg is None:
            raise KeyError(f"unknown condition {condition!r}")
        return str(cfg.get("description", condition))

    def all_conditions(self) -> Dict[str, Dict[str, object]]:
        return dict(self._conditions)

    @contextlib.contextmanager
    def apply(self, condition: str, pipeline: "PragmaBot") -> Iterator[None]:
        """Context manager — flips ``activate_stm`` / ``activate_ltm`` for the run."""
        cfg = self._conditions.get(condition)
        if cfg is None:
            raise KeyError(f"unknown condition {condition!r}")

        prev_stm = pipeline.activate_stm
        prev_ltm = pipeline.activate_ltm
        try:
            pipeline.activate_stm = bool(cfg["use_stm"])
            pipeline.activate_ltm = bool(cfg["use_ltm"])
            yield
        finally:
            # Always restore — even if the trial raised.
            pipeline.activate_stm = prev_stm
            pipeline.activate_ltm = prev_ltm
