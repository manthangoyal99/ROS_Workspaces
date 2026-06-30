"""Factory for grasp synthesizers — delegates to the global registry."""

from __future__ import annotations

from omegaconf import DictConfig

from ...registry import registry
from .base import BaseGraspSynthesizer


def get_grasp_synthesizer(cfg: DictConfig) -> BaseGraspSynthesizer:
    backend = "top_down"
    if "robot" in cfg and "grasp" in cfg.robot:
        backend = str(cfg.robot.grasp.get("backend", "top_down")).lower()

    if backend == "anygrasp":
        raise NotImplementedError(
            "AnyGrasp synthesizer is not implemented yet (planned for Phase 7+). "
            "Use grasp.backend: top_down for now."
        )
    cls = registry.get("grasp", backend)
    return cls(cfg)
