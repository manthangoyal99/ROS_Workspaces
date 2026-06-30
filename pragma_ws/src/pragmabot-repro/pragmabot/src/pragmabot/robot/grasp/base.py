"""Abstract grasp synthesizer interface.

This is intentionally Mac-safe (pure numpy). The robot backend (FrankaRobot)
consumes ``GraspCandidate`` objects and applies an IK feasibility filter
itself; the synthesizer only proposes candidates. The split lets us swap in
AnyGrasp or any learned policy in a later phase without touching the skill
execution code.

The paper's equation (6) ranks candidates as ``g* = argmax sconf(g) * sloc(g)``
— see :meth:`BaseGraspSynthesizer.synthesize` for how each backend should
populate ``confidence``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional

import numpy as np


@dataclass
class GraspCandidate:
    """One candidate grasp pose in the robot base frame.

    Attributes:
        pose_matrix: 4x4 SE(3) matrix. The translation column is the grasp
            position; the rotation columns define the end-effector frame
            (x-right, y-down, z-forward toward object for a top-down grasp).
        confidence: Synthesizer-defined confidence in [0, 1].
        approach_vector: Unit vector (3,) along which the gripper should
            approach the grasp pose (in the robot base frame).
        extras: Backend-specific metadata.
    """

    pose_matrix: np.ndarray
    confidence: float
    approach_vector: np.ndarray
    extras: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.pose_matrix, np.ndarray) or self.pose_matrix.shape != (4, 4):
            raise ValueError(
                f"pose_matrix must be a 4x4 ndarray, got {getattr(self.pose_matrix, 'shape', None)}"
            )
        if not isinstance(self.approach_vector, np.ndarray) or self.approach_vector.shape != (3,):
            raise ValueError(
                f"approach_vector must be a (3,) ndarray, got {getattr(self.approach_vector, 'shape', None)}"
            )
        self.confidence = float(self.confidence)

    @property
    def position(self) -> np.ndarray:
        return self.pose_matrix[:3, 3].copy()

    @property
    def rotation(self) -> np.ndarray:
        return self.pose_matrix[:3, :3].copy()


class BaseGraspSynthesizer(ABC):
    """Abstract grasp synthesizer."""

    @abstractmethod
    def synthesize(
        self,
        object_name: str,
        point_cloud: Optional[np.ndarray] = None,
        target_position: Optional[np.ndarray] = None,
    ) -> List[GraspCandidate]:
        """Return ranked grasp candidates (highest confidence first).

        Args:
            object_name: Label of the target object (informational).
            point_cloud: Optional (N, 3) point cloud of the object surface
                in the robot base frame. Some backends require this.
            target_position: Optional (3,) position of the object centroid
                in the robot base frame. Used as a fallback when no point
                cloud is available.
        """

    def filter_by_ik(
        self,
        candidates: List[GraspCandidate],
        ik_check_fn: Callable[[np.ndarray], bool],
    ) -> List[GraspCandidate]:
        """Keep only candidates whose pose passes ``ik_check_fn(pose_matrix)``."""
        return [c for c in candidates if ik_check_fn(c.pose_matrix)]

    @property
    @abstractmethod
    def backend_name(self) -> str:
        """Short identifier (e.g., ``"top_down"``)."""
