"""Deterministic stub VLM — used for unit tests and offline dev.

The stub recognises the four pipeline prompts (scene description, planning,
success detection, experience summarization) by either the system role or
keywords in the user prompt, and returns shape-correct responses that match
what the planning modules expect to parse.
"""

from __future__ import annotations

import hashlib
import json
from typing import List

import numpy as np

from .base import BaseVLM


def _flatten_messages(messages: List[dict]) -> str:
    """Stable text serialization of a chat message list."""
    parts: List[str] = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if isinstance(content, list):
            # OpenAI multimodal-style content (list of parts)
            bits: List[str] = []
            for part in content:
                if isinstance(part, dict):
                    t = part.get("type")
                    if t == "text":
                        bits.append(str(part.get("text", "")))
                    elif t == "image_url":
                        bits.append("[image]")
                    else:
                        bits.append(json.dumps(part, sort_keys=True))
                else:
                    bits.append(str(part))
            content = " ".join(bits)
        parts.append(f"{role}: {content}")
    return "\n".join(parts)


def _last_user_text(messages: List[dict]) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            content = m.get("content", "")
            if isinstance(content, list):
                parts: List[str] = []
                for p in content:
                    if isinstance(p, dict) and p.get("type") == "text":
                        parts.append(str(p.get("text", "")))
                return " ".join(parts)
            return str(content)
    return ""


class StubVLM(BaseVLM):
    """Deterministic stub.

    Detector responses cycle ``task_complete`` (False, True, False, True, ...)
    so the pipeline can be driven to either succeed at a chosen step or run
    until max_steps. The cycle is configurable via the ``detector_mode``
    keyword:

    - ``"alternating"`` (default): cycles False, True, ...
    - ``"never_complete"``: always False
    - ``"always_complete"``: always True
    - ``"complete_at:<N>"``: True on the N-th call, False otherwise
    """

    def __init__(
        self,
        model: str = "stub",
        temperature: float = 0.0,
        max_tokens: int = 512,
        detector_mode: str = "alternating",
        planner_skill: str = "pick",
        planner_object: str = "apple",
    ) -> None:
        super().__init__()
        self.model = model
        self.temperature = float(temperature)
        self.max_tokens = int(max_tokens)
        self.detector_mode = str(detector_mode)
        self.planner_skill = planner_skill
        self.planner_object = planner_object
        self._detector_calls = 0
        self._planner_calls = 0
        # Public list of every received prompt — useful for assertions in tests.
        self.received_prompts: List[str] = []

    @property
    def backend_name(self) -> str:
        return "stub"

    # ------------------------------------------------------------------
    # Routing helpers
    # ------------------------------------------------------------------

    def _is_planner(self, last_user: str, flat: str) -> bool:
        if "task planner" in flat:
            return True
        # The planner JSON template literally contains the word "skill".
        return "skill" in last_user.lower()

    def _is_detector(self, last_user: str, flat: str) -> bool:
        if "success detector" in flat:
            return True
        return "action_success" in last_user.lower()

    def _is_scene(self, flat: str) -> bool:
        return "scene observer" in flat or "visual perception system" in flat

    def _is_summarizer(self, flat: str) -> bool:
        return "experience summarizer" in flat or "experience summarizer" in flat

    # ------------------------------------------------------------------
    # Response builders
    # ------------------------------------------------------------------

    def _planner_response(self) -> str:
        self._planner_calls += 1
        params: dict
        if self.planner_skill == "pick":
            params = {"object": self.planner_object, "use_annotation": False}
        elif self.planner_skill == "place":
            params = {
                "object": self.planner_object,
                "location": "plate",
                "use_annotation": False,
            }
        elif self.planner_skill == "push":
            params = {
                "object": self.planner_object,
                "direction": "right",
                "use_annotation": False,
            }
        else:  # pragma: no cover - safety fallback
            params = {"object": self.planner_object}
        payload = {
            "skill": self.planner_skill,
            "parameters": params,
            "reasoning": (
                f"Chose {self.planner_skill} of {self.planner_object} given the "
                "instruction and the current scene observation."
            ),
        }
        return json.dumps(payload)

    def _detector_response(self) -> str:
        self._detector_calls += 1
        n = self._detector_calls
        mode = self.detector_mode
        if mode == "alternating":
            task_complete = (n % 2) == 0
        elif mode == "never_complete":
            task_complete = False
        elif mode == "always_complete":
            task_complete = True
        elif mode.startswith("complete_at:"):
            try:
                target = int(mode.split(":", 1)[1])
            except ValueError:
                target = 0
            task_complete = n == target
        else:
            task_complete = False
        payload = {
            "action_success": True,
            "task_complete": bool(task_complete),
            "scene_change": "Object appears at the target location.",
            "reasoning": f"Stub detector call #{n}, mode={mode}.",
        }
        return json.dumps(payload)

    def _scene_response(self) -> str:
        return (
            "Scene: a tabletop with one red apple, one blue cup, "
            "and a wooden block arranged left-to-right."
        )

    def _summary_response(self) -> str:
        return (
            "Experience: picked the apple after observing it on the left side "
            "of the table; one attempt sufficed."
        )

    # ------------------------------------------------------------------
    # Main dispatch
    # ------------------------------------------------------------------

    def _route(self, messages: List[dict], with_image: bool) -> str:
        flat = _flatten_messages(messages).lower()
        last_user = _last_user_text(messages)
        self.received_prompts.append(last_user)

        # Detector first — it's the only stage with two images and its content
        # has the most distinctive marker (``action_success``).
        if self._is_detector(last_user, flat):
            return self._detector_response()
        if self._is_planner(last_user, flat):
            return self._planner_response()
        if self._is_scene(flat):
            return self._scene_response()
        if self._is_summarizer(flat):
            return self._summary_response()

        # Fallback — deterministic short hash response.
        digest = hashlib.sha256(flat.encode("utf-8")).hexdigest()[:8]
        prefix = "[stub+img]" if with_image else "[stub]"
        return f"{prefix} response-{digest}"

    def chat(self, messages: List[dict]) -> str:
        resp = self._route(messages, with_image=False)
        self._record_exchange(messages, resp, images=None)
        return resp

    def chat_with_image(self, messages: List[dict], images: List[np.ndarray]) -> str:
        if images:
            shape_tag = "|".join(
                f"{img.shape}-{int(img.mean())}" for img in images if isinstance(img, np.ndarray)
            )
            messages = list(messages) + [
                {"role": "system", "content": f"[image-tag {shape_tag}]"}
            ]
        resp = self._route(messages, with_image=True)
        self._record_exchange(messages, resp, images=images)
        return resp
