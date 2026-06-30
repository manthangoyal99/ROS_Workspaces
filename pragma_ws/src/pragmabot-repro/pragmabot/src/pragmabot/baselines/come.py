"""COME baseline — closed-loop VLM with no memory.

In our reproduction this is identical to CaP-V (same use_stm=False,
use_ltm=False). The paper distinguishes them by citation only; we keep the
two classes separate so the eval condition label maps 1:1 to the table.

Paper reference: §V.C, Table III baseline. Zhi et al., arXiv:2404.10220.
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


@registry.register("baseline", "come")
class COMEBaseline(BaseBaseline):
    """Closed-loop VLM planner with empty STM / empty LTM."""

    def __init__(self, vlm: BaseVLM, cfg: DictConfig) -> None:
        self.vlm = vlm
        self.cfg = cfg
        self._planner = VLMTaskPlanner(vlm, cfg)

    @property
    def baseline_name(self) -> str:
        return "come"

    def reset(self) -> None:
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
            stm=ShortTermMemory(),
            ltm_entries=[],
            available_skills=list(available_skills),
            detected_objects=None,
        )
