"""Top-down grasp synthesizer — the Phase 4 default.

Generates a single grasp directly above the target with the gripper's
z-axis pointing into the table (approach vector ``[0, 0, -1]`` in the
robot base frame). No point cloud required; AnyGrasp can replace this in
Phase 7 without touching FrankaRobot.
"""

from __future__ import annotations

from typing import List, Optional

import numpy as np
from omegaconf import DictConfig

from .base import BaseGraspSynthesizer, GraspCandidate


def _top_down_pose(position: np.ndarray, approach_height: float, depth_offset: float) -> np.ndarray:
    """Build a 4x4 grasp pose AT ``position`` with EE-down rotation.

    The returned pose is the **grasp** pose — the EE position where the
    gripper closes on the object — not the pre-grasp / approach pose. The
    caller (``FrankaRobot.execute_pick``) is responsible for adding its own
    ``approach_height_offset`` when building the pre-grasp pose.

    ``depth_offset`` is the sink-into-object depth (subtracted from z): a
    positive value drives the gripper slightly below the perceived centroid
    so the fingers wrap around the body of a round object.

    ``approach_height`` is retained in the signature for backwards
    compatibility but is intentionally **not** added to the grasp z. (Earlier
    versions of this function added it, which produced a grasp pose at the
    approach height and caused the arm to never descend to the object — see
    the experiment log entry "no descent on real Franka".)
    """
    pose = np.eye(4, dtype=float)
    pose[:3, :3] = np.array(
        [
            [1.0, 0.0, 0.0],   # ee X = base X
            [0.0, -1.0, 0.0],  # ee Y = -base Y (flip)
            [0.0, 0.0, -1.0],  # ee Z = -base Z (down)
        ],
        dtype=float,
    )
    pose[:3, 3] = np.asarray(position, dtype=float).reshape(3) + np.array(
        [0.0, 0.0, -depth_offset], dtype=float
    )
    return pose


class TopDownGraspSynthesizer(BaseGraspSynthesizer):
    """Single-candidate top-down grasp synthesizer."""

    def __init__(self, cfg: Optional[DictConfig] = None) -> None:
        grasp_cfg = None
        if cfg is not None and "robot" in cfg and "grasp" in cfg.robot:
            grasp_cfg = cfg.robot.grasp
        if grasp_cfg is None and cfg is not None and "grasp" in cfg:
            grasp_cfg = cfg.grasp
        self.approach_height: float = float(
            grasp_cfg.get("approach_height", 0.12) if grasp_cfg is not None else 0.12
        )
        self.grasp_height_offset: float = float(
            grasp_cfg.get("grasp_height_offset", 0.005) if grasp_cfg is not None else 0.005
        )

    @property
    def backend_name(self) -> str:
        return "top_down"

    def synthesize(
        self,
        object_name: str,
        point_cloud: Optional[np.ndarray] = None,
        target_position: Optional[np.ndarray] = None,
    ) -> List[GraspCandidate]:
        # Prefer the cloud's centroid when both are provided; fall back to target.
        if point_cloud is not None and np.asarray(point_cloud).size > 0:
            arr = np.asarray(point_cloud, dtype=float)
            if arr.ndim != 2 or arr.shape[1] != 3:
                raise ValueError(f"point_cloud must be (N, 3), got {arr.shape}")
            position = arr.mean(axis=0)
        elif target_position is not None:
            position = np.asarray(target_position, dtype=float).reshape(-1)
            if position.shape != (3,):
                raise ValueError(f"target_position must be (3,), got {position.shape}")
        else:
            return []

        pose_matrix = _top_down_pose(position, self.approach_height, self.grasp_height_offset)
        candidate = GraspCandidate(
            pose_matrix=pose_matrix,
            confidence=1.0,
            approach_vector=np.array([0.0, 0.0, -1.0], dtype=float),
            extras={"object_name": object_name, "synthesizer": "top_down"},
        )
        return [candidate]
