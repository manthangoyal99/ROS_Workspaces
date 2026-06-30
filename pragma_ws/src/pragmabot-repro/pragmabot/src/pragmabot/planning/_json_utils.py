"""Robust JSON extraction helpers for VLM responses."""

from __future__ import annotations

import json
import re
from typing import Any

from ..errors import VLMOutputParseError

_FENCE_RE = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.DOTALL)


def _strip_fences(raw: str) -> str:
    """Strip the first ```json ... ``` fenced block if present, else return raw."""
    m = _FENCE_RE.search(raw)
    if m:
        return m.group(1).strip()
    return raw.strip()


def _find_first_object(text: str) -> str | None:
    """Find the first balanced ``{...}`` JSON object substring."""
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(text)):
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def parse_json_object(raw: str, context: str = "") -> dict:
    """Parse a JSON object from a VLM response.

    Handles markdown fences, leading/trailing prose, and embedded objects.

    Args:
        raw: The raw VLM string.
        context: Human-readable context for error messages (e.g., ``"task_planner"``).

    Returns:
        The parsed dict.

    Raises:
        VLMOutputParseError: If no valid JSON object can be extracted.
    """
    if not isinstance(raw, str):
        raise VLMOutputParseError(f"[{context}] expected str VLM output, got {type(raw).__name__}", raw=str(raw))

    candidate = _strip_fences(raw)
    try:
        data = json.loads(candidate)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, ValueError):
        pass

    sub = _find_first_object(candidate) or _find_first_object(raw)
    if sub is None:
        raise VLMOutputParseError(f"[{context}] no JSON object found in VLM output", raw=raw)
    try:
        data = json.loads(sub)
    except (json.JSONDecodeError, ValueError) as exc:
        raise VLMOutputParseError(f"[{context}] failed to parse JSON: {exc}", raw=raw) from exc
    if not isinstance(data, dict):
        raise VLMOutputParseError(f"[{context}] parsed value is not a JSON object", raw=raw)
    return data
