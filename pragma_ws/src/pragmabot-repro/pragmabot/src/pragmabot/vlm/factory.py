"""Factory for VLM backends — delegates to the global ComponentRegistry."""

from __future__ import annotations

import logging

from omegaconf import DictConfig

from ..registry import registry
from .base import BaseVLM
from .stub_vlm import StubVLM  # noqa: F401  (ensures default registration)

logger = logging.getLogger(__name__)


def get_vlm(cfg: DictConfig) -> BaseVLM:
    """Instantiate the VLM backend named in ``cfg.vlm.backend``."""
    vlm_cfg = cfg.vlm
    backend = str(vlm_cfg.get("backend", "stub")).lower()
    model = str(vlm_cfg.get("model", "stub"))
    temperature = float(vlm_cfg.get("temperature", 0.0))
    max_tokens = int(vlm_cfg.get("max_tokens", 512))

    cls = registry.get("vlm", backend)
    if backend == "stub":
        return cls(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            detector_mode=str(vlm_cfg.get("detector_mode", "alternating")),
            planner_skill=str(vlm_cfg.get("planner_skill", "pick")),
            planner_object=str(vlm_cfg.get("planner_object", "apple")),
        )
    if backend == "ollama":
        return cls(
            model=model,
            host=str(vlm_cfg.get("ollama_host", "http://localhost:11434")),
            temperature=temperature,
            max_tokens=max_tokens,
        )
    if backend == "openai":
        return cls(model=model, temperature=temperature, max_tokens=max_tokens)

    # Anything registered by the user falls through here.
    return cls(cfg)
