"""Factory for baseline planners — delegates to the global registry."""

from __future__ import annotations

from omegaconf import DictConfig

from ..registry import registry
from ..vlm.base import BaseVLM
from .base import BaseBaseline


def get_baseline(name: str, vlm: BaseVLM, cfg: DictConfig) -> BaseBaseline:
    cls = registry.get("baseline", name)
    return cls(vlm=vlm, cfg=cfg)
