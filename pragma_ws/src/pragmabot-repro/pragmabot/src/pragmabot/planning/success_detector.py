"""Before/after success detector — wraps a VLM."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

import numpy as np
from omegaconf import DictConfig

from ..errors import VLMOutputParseError
from ..vlm.base import BaseVLM
from ._json_utils import parse_json_object

logger = logging.getLogger(__name__)


def _describe_action(action: Dict[str, Any]) -> str:
    skill = action.get("skill", "noop")
    params = action.get("parameters", {})
    try:
        params_str = json.dumps(params, sort_keys=True)
    except (TypeError, ValueError):
        params_str = str(params)
    return f"{skill} with parameters {params_str}"


class VLMSuccessDetector:
    """Decide whether an action succeeded and whether the task is now complete."""

    def __init__(self, vlm: BaseVLM, cfg: DictConfig) -> None:
        self.vlm = vlm
        self.cfg = cfg
        self.prompt_template: str = str(cfg.prompts.success_detector)

    def evaluate(
        self,
        instruction: str,
        action: Dict[str, Any],
        before_image: np.ndarray,
        after_image: np.ndarray,
    ) -> Dict[str, Any]:
        prompt = self.prompt_template.format(
            instruction=instruction,
            action_description=_describe_action(action),
        )
        messages: List[dict] = [
            {"role": "system", "content": "You are a robot success detector."},
            {"role": "user", "content": prompt},
        ]
        raw = self.vlm.chat_with_image(messages, [before_image, after_image])
        try:
            data = parse_json_object(raw, context="success_detector")
        except VLMOutputParseError:
            logger.warning("Success detector returned unparseable output; raising.")
            raise

        out = {
            "action_success": bool(data.get("action_success", False)),
            "task_complete": bool(data.get("task_complete", False)),
            "scene_change": str(data.get("scene_change", "")),
            "reasoning": str(data.get("reasoning", "")),
        }
        return out
