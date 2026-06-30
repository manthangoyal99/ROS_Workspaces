"""CaP-V baseline — VLMTaskPlanner with STM and LTM forced to empty.

Paper reference: §V.B, Table II baseline. Code-as-Policies for VLM, no memory.
"""

from __future__ import annotations

from typing import Any, Dict, List

import numpy as np
from omegaconf import DictConfig

from ..memory.stm import ShortTermMemory
from ..planning.task_planner import VLMTaskPlanner
from ..registry import registry
from ..vlm.base import BaseVLM
from .base import BaseBaseline


@registry.register("baseline", "cap_v")
class CaPVBaseline(BaseBaseline):
    """Thin wrapper around ``VLMTaskPlanner`` with empty STM / empty LTM."""

    def __init__(self, vlm: BaseVLM, cfg: DictConfig) -> None:
        self.vlm = vlm
        self.cfg = cfg
        self._planner = VLMTaskPlanner(vlm, cfg)

    @property
    def baseline_name(self) -> str:
        return "cap_v"

    def reset(self) -> None:
        # Stateless — nothing to reset.
        return None

    def plan(
        self,
        instruction: str,
        image: np.ndarray,
        available_skills: List[str],
    ) -> Dict[str, Any]:
        return self._planner.plan(
            instruction=instruction,
            image=image,
            stm=ShortTermMemory(),  # empty — that's the point
            ltm_entries=[],          # empty — that's the point
            available_skills=list(available_skills),
            detected_objects=None,
        )
