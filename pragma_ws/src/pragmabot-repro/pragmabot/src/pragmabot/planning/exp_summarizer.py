"""Distill a finished STM into a reusable LTM experience entry."""

from __future__ import annotations

import logging
from typing import List

from omegaconf import DictConfig

from ..memory.stm import ShortTermMemory
from ..vlm.base import BaseVLM

logger = logging.getLogger(__name__)


class VLMExperienceSummarizer:
    """Compress one task run into a compact, reusable lesson."""

    def __init__(self, vlm: BaseVLM, cfg: DictConfig) -> None:
        self.vlm = vlm
        self.cfg = cfg
        self.prompt_template: str = str(cfg.prompts.exp_summarizer)

    def summarize(
        self,
        instruction: str,
        scene_description: str,
        stm: ShortTermMemory,
    ) -> str:
        stm_text = stm.to_text() if not stm.is_empty() else "(no steps recorded)"
        prompt = self.prompt_template.format(
            instruction=instruction,
            scene_description=scene_description,
            stm_text=stm_text,
        )
        messages: List[dict] = [
            {"role": "system", "content": "You are an experience summarizer."},
            {"role": "user", "content": prompt},
        ]
        out = self.vlm.chat(messages)
        return out.strip() if isinstance(out, str) else str(out)
