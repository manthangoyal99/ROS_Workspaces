"""Factory for perception backends — delegates to the global registry."""

from __future__ import annotations

from omegaconf import DictConfig

from ..registry import registry
from .base import BasePerception


def get_perception(cfg: DictConfig) -> BasePerception:
    backend = str(cfg.perception.get("backend", "stub")).lower()
    try:
        cls = registry.get("perception", backend)
    except KeyError as exc:
        if backend == "grounded_sam":
            raise RuntimeError(
                "Requested perception.backend=grounded_sam but dependencies "
                "are missing. Install torch, groundingdino-py, and "
                "segment-anything (see docs/setup_ubuntu.md), or fall back "
                "to perception.backend=stub."
            ) from exc
        raise
    try:
        return cls(cfg)
    except ImportError as exc:
        if backend == "grounded_sam":
            raise RuntimeError(
                "Requested perception.backend=grounded_sam but dependencies "
                "are missing. Install torch, groundingdino-py, and "
                "segment-anything (see docs/setup_ubuntu.md), or fall back "
                "to perception.backend=stub."
            ) from exc
        raise
