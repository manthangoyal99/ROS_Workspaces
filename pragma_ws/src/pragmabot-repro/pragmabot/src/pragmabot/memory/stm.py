"""Short-term memory — episodic action+feedback log for one task run."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List


@dataclass
class STMEntry:
    """One step of the task: the action proposed and its observed feedback."""

    action: Dict[str, Any]
    feedback: Dict[str, Any]
    step: int

    def to_dict(self) -> Dict[str, Any]:
        return {"step": self.step, "action": dict(self.action), "feedback": dict(self.feedback)}


class ShortTermMemory:
    """Per-task action history. Reset between tasks."""

    def __init__(self) -> None:
        self._entries: List[STMEntry] = []

    def append(self, action: Dict[str, Any], feedback: Dict[str, Any]) -> None:
        """Append a new (action, feedback) pair as the next step."""
        if not isinstance(action, dict):
            raise TypeError("action must be a dict")
        if not isinstance(feedback, dict):
            raise TypeError("feedback must be a dict")
        step = len(self._entries) + 1
        self._entries.append(STMEntry(action=dict(action), feedback=dict(feedback), step=step))

    def reset(self) -> None:
        """Clear all entries."""
        self._entries = []

    def is_empty(self) -> bool:
        return len(self._entries) == 0

    def last(self) -> STMEntry | None:
        return self._entries[-1] if self._entries else None

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self) -> Iterator[STMEntry]:
        return iter(self._entries)

    def to_list(self) -> List[Dict[str, Any]]:
        """Serializable list of entry dicts (for inclusion in result payloads)."""
        return [e.to_dict() for e in self._entries]

    # ------------------------------------------------------------------
    # Text formatting for VLM prompt injection
    # ------------------------------------------------------------------

    @staticmethod
    def _format_action(action: Dict[str, Any]) -> str:
        """Render an action dict as ``skill(arg1, arg2=...)``-style text."""
        skill = action.get("skill") or action.get("action") or "noop"
        params = action.get("parameters") or {}
        if not isinstance(params, dict):
            return f"{skill}({params})"
        # Common shorthand:
        if skill == "pick" and "object" in params:
            return f"pick({params['object']})"
        if skill == "place" and "object" in params:
            loc = params.get("location", "?")
            return f"place({params['object']}, {loc})"
        if skill == "push" and "object" in params:
            direction = params.get("direction", "?")
            return f"push({params['object']}, {direction})"
        # Fallback: generic key=value list.
        body = ", ".join(f"{k}={v}" for k, v in params.items())
        return f"{skill}({body})"

    @staticmethod
    def _format_result(feedback: Dict[str, Any]) -> str:
        success = feedback.get("action_success")
        if success is True:
            return "SUCCESS"
        if success is False:
            return "FAILED"
        return "UNKNOWN"

    def to_text(self) -> str:
        """Format STM as human-readable text for VLM prompt injection.

        Format (one step per line):
            Step N: Action: <skill(params)>. Result: <SUCCESS|FAILED|UNKNOWN>.
            Scene change: <text>.

        Returns an empty string when STM is empty.
        """
        if not self._entries:
            return ""
        lines: List[str] = []
        for entry in self._entries:
            action_str = self._format_action(entry.action)
            result = self._format_result(entry.feedback)
            scene_change = str(entry.feedback.get("scene_change") or "(none)")
            lines.append(
                f"Step {entry.step}: Action: {action_str}. Result: {result}. "
                f"Scene change: {scene_change}"
            )
        return "\n".join(lines)
