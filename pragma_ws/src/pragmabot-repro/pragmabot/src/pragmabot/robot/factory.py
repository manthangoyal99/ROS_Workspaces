"""Factory for robot backends — delegates to the global ComponentRegistry."""

from __future__ import annotations

import logging

from omegaconf import DictConfig

from ..registry import registry
from .base import BaseRobot

logger = logging.getLogger(__name__)


def get_robot(cfg: DictConfig) -> BaseRobot:
    backend = str(cfg.robot.get("backend", "stub")).lower()
    if backend == "franka_ros":
        # Ensure the franka_ros class is loaded (and the constructor fires
        # the friendly RuntimeError on Mac if ROS is missing).
        from .franka_ros import FrankaRobot

        return FrankaRobot(cfg)
    cls = registry.get("robot", backend)
    return cls(cfg=cfg)
