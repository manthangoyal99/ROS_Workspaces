"""Stub robot — no ROS, deterministic, logs every call."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import numpy as np
from omegaconf import DictConfig

from .base import BaseRobot

# ROS guard per CLAUDE.md — this stub does not import ROS but follows the
# documented pattern so the file is safe to import on Ubuntu later.
try:
    import rospy  # type: ignore  # noqa: F401

    ROS_AVAILABLE = True
except ImportError:
    ROS_AVAILABLE = False


logger = logging.getLogger(__name__)


class StubRobot(BaseRobot):
    """No-op robot — every call is appended to ``execution_log``."""

    def __init__(
        self,
        cfg: Optional[DictConfig] = None,
        always_succeed: bool = True,
        observation_shape: tuple[int, int, int] = (480, 640, 3),
    ) -> None:
        self.cfg = cfg
        self.always_succeed = bool(always_succeed)
        self.observation_shape = observation_shape
        self.execution_log: List[Dict[str, Any]] = []

    @property
    def backend_name(self) -> str:
        return "stub"

    # ------------------------------------------------------------------
    # Skill execution
    # ------------------------------------------------------------------

    def _log(self, skill: str, **kwargs: Any) -> None:
        self.execution_log.append({"skill": skill, "parameters": dict(kwargs)})

    @staticmethod
    def _xyz(value: Any) -> Optional[list]:
        if value is None:
            return None
        arr = np.asarray(value, dtype=float).reshape(-1)
        return [float(c) for c in arr]

    def execute_pick(
        self,
        object_name: str,
        target_position_3d: Optional[np.ndarray] = None,
        location_hint: Optional[str] = None,
    ) -> bool:
        logger.info(
            "[stub-robot] pick(%s, pos=%s, hint=%s)",
            object_name,
            target_position_3d,
            location_hint,
        )
        self._log(
            "pick",
            object=object_name,
            target_position_3d=self._xyz(target_position_3d),
            location_hint=location_hint,
        )
        return self.always_succeed

    def execute_place(
        self,
        object_name: str,
        target_position_3d: Optional[np.ndarray] = None,
        location: Optional[str] = None,
    ) -> bool:
        logger.info(
            "[stub-robot] place(%s, pos=%s, location=%s)",
            object_name,
            target_position_3d,
            location,
        )
        self._log(
            "place",
            object=object_name,
            target_position_3d=self._xyz(target_position_3d),
            location=location,
        )
        return self.always_succeed

    def execute_push(
        self,
        object_name: str,
        goal_position_3d: Optional[np.ndarray] = None,
        direction: Optional[str] = None,
    ) -> bool:
        logger.info(
            "[stub-robot] push(%s, goal=%s, direction=%s)",
            object_name,
            goal_position_3d,
            direction,
        )
        self._log(
            "push",
            object=object_name,
            goal_position_3d=self._xyz(goal_position_3d),
            direction=direction,
        )
        return self.always_succeed

    # ------------------------------------------------------------------
    # Observation + connection
    # ------------------------------------------------------------------

    def _native_observation(self) -> np.ndarray:
        return np.zeros(self.observation_shape, dtype=np.uint8)

    def is_connected(self) -> bool:
        return True
