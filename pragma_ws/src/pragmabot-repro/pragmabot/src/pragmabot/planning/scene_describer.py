"""VLM-driven initial scene describer."""

from __future__ import annotations

import logging
from typing import List

import numpy as np
from omegaconf import DictConfig

from ..vlm.base import BaseVLM

logger = logging.getLogger(__name__)


class VLMSceneDescriber:
    """Produce a 1-3 sentence description of an RGB image."""

    def __init__(self, vlm: BaseVLM, cfg: DictConfig) -> None:
        self.vlm = vlm
        self.cfg = cfg
        self.prompt_template: str = str(cfg.prompts.scene_describer)

    def describe(self, image: np.ndarray, instruction: str) -> str:
        prompt = self.prompt_template.format(instruction=instruction)
        messages: List[dict] = [
            {"role": "system", "content": "You are a robot scene observer."},
            {"role": "user", "content": prompt},
        ]
        out = self.vlm.chat_with_image(messages, [image])
        return out.strip() if isinstance(out, str) else str(out)
