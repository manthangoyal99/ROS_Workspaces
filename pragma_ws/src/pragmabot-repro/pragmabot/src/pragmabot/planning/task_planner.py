"""STM-aware, LTM-RAG-augmented task planner."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List

import numpy as np
from omegaconf import DictConfig

from ..errors import VLMOutputParseError
from ..memory.stm import ShortTermMemory
from ..perception.base import DetectedObject
from ..vlm.base import BaseVLM
from ._json_utils import _find_first_object  # noqa: F401 — reused below

logger = logging.getLogger(__name__)


_FENCE_RE = re.compile(r"```(?:json|JSON)?\s*", re.IGNORECASE)
_CLOSING_FENCE_RE = re.compile(r"```\s*")


class VLMTaskPlanner:
    """Plan the next robot action via a VLM, using STM (current run) and LTM (RAG)."""

    def __init__(self, vlm: BaseVLM, cfg: DictConfig) -> None:
        self.vlm = vlm
        self.cfg = cfg
        prompts = cfg.prompts
        self.planner_template: str = str(prompts.task_planner)
        self.reflection_template: str = str(prompts.task_planner_reflection)
        self.ltm_template: str = str(prompts.task_planner_ltm)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def plan(
        self,
        instruction: str,
        image: np.ndarray,
        stm: ShortTermMemory,
        ltm_entries: List[dict],
        available_skills: List[str],
        detected_objects: List[DetectedObject] | None = None,
    ) -> Dict[str, Any]:
        messages = self._build_prompt(
            instruction=instruction,
            stm=stm,
            ltm_entries=ltm_entries,
            available_skills=list(available_skills),
            detected_objects=detected_objects or [],
        )
        raw = self.vlm.chat_with_image(messages, [image])
        try:
            data = self._extract_json(raw)
        except VLMOutputParseError:
            logger.warning("Task planner returned unparseable output; raising.")
            raise

        skill = data.get("skill")
        if not isinstance(skill, str):
            raise VLMOutputParseError(
                "task_planner output missing 'skill' string", raw=raw
            )
        if available_skills and skill not in available_skills:
            raise VLMOutputParseError(
                f"task_planner produced unknown skill {skill!r}; "
                f"available={available_skills}",
                raw=raw,
            )
        parameters = data.get("parameters", {})
        if not isinstance(parameters, dict):
            raise VLMOutputParseError(
                "task_planner output 'parameters' must be a JSON object", raw=raw
            )
        reasoning = data.get("reasoning", "")
        if not isinstance(reasoning, str):
            reasoning = json.dumps(reasoning)
        return {"skill": skill, "parameters": parameters, "reasoning": reasoning}

    # ------------------------------------------------------------------
    # JSON extraction (robust against prose-wrapped or fence-wrapped output)
    # ------------------------------------------------------------------

    def _extract_json(self, text: str) -> Dict[str, Any]:
        """Extract the first JSON object from a VLM response.

        Tolerates: surrounding prose, markdown fences (``"```json"`` /
        ``"```"``), duplicate fences, leading/trailing whitespace, and
        nested objects. After stripping fences, tries direct ``json.loads``;
        if that fails, falls back to a balanced-brace scan.

        Raises:
            VLMOutputParseError: if no JSON object can be recovered.
        """
        if not isinstance(text, str):
            raise VLMOutputParseError(
                f"[task_planner] expected str VLM output, got {type(text).__name__}",
                raw=str(text),
            )

        # Strip all triple-backtick fences (open or close, any language tag).
        cleaned = _FENCE_RE.sub("", text)
        cleaned = _CLOSING_FENCE_RE.sub("", cleaned)
        cleaned = cleaned.strip()

        # 1. Direct parse — fastest path when the model behaves.
        try:
            data = json.loads(cleaned)
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, ValueError):
            pass

        # 2. Balanced-brace scan over the cleaned text, then the raw text.
        for candidate_text in (cleaned, text):
            sub = _find_first_object(candidate_text)
            if sub is None:
                continue
            try:
                data = json.loads(sub)
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(data, dict):
                return data

        head = text[:200].replace("\n", " ")
        raise VLMOutputParseError(
            f"[task_planner] no JSON object found in VLM output: {head!r}",
            raw=text,
        )

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _build_prompt(
        self,
        instruction: str,
        stm: ShortTermMemory,
        ltm_entries: List[dict],
        available_skills: List[str],
        detected_objects: List[DetectedObject],
    ) -> List[dict]:
        ltm_section = self._format_ltm(ltm_entries)
        stm_text = stm.to_text() if not stm.is_empty() else "(no prior actions in this run)"

        last = stm.last()
        last_failed = last is not None and last.feedback.get("action_success") is False
        reflection = self.reflection_template.strip() if last_failed else ""

        skills_str = ", ".join(available_skills) if available_skills else "(none)"

        user_prompt = self.planner_template.format(
            instruction=instruction,
            available_skills=skills_str,
            ltm_section=ltm_section,
            stm_text=stm_text,
            reflection_instruction=reflection,
        )

        if detected_objects:
            user_prompt = user_prompt + "\n\n" + self._format_detected_objects(detected_objects)

        return [
            {"role": "system", "content": "You are a robot task planner."},
            {"role": "user", "content": user_prompt},
        ]

    @staticmethod
    def _format_detected_objects(detected_objects: List[DetectedObject]) -> str:
        lines = ["Detected objects (from perception):"]
        for obj in detected_objects:
            xyz = (
                "unknown"
                if obj.centroid_3d is None
                else f"({obj.centroid_3d[0]:.3f}, {obj.centroid_3d[1]:.3f}, {obj.centroid_3d[2]:.3f}) m"
            )
            lines.append(
                f"- {obj.name}: bbox={obj.bbox_2d}, centroid_2d={obj.centroid_2d}, "
                f"centroid_3d={xyz}, confidence={obj.confidence:.2f}"
            )
        return "\n".join(lines)

    def _format_ltm(self, ltm_entries: List[dict]) -> str:
        if not ltm_entries:
            return ""
        rendered: List[str] = []
        for e in ltm_entries:
            key = e.get("key", "")
            experience = e.get("experience", "")
            sim = e.get("similarity")
            sim_str = f" (similarity={sim:.3f})" if isinstance(sim, (int, float)) else ""
            rendered.append(f"- key: {key}{sim_str}\n  experience: {experience}")
        experiences = "\n".join(rendered)
        return self.ltm_template.format(experiences=experiences)
