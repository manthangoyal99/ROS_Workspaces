"""Per-episode JSON logger.

Each call to :meth:`EpisodeLogger.start_episode` opens a new episode and
returns its ID; subsequent ``log_step`` calls accumulate into the current
episode buffer, and ``end_episode`` writes the final JSON to ``log_dir``.

The output shape is documented in the class docstring.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging as _stdlib_logging
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from omegaconf import DictConfig, OmegaConf

from ..utils import ensure_dir

logger = _stdlib_logging.getLogger(__name__)


def _now_iso() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def _to_jsonable(value: Any) -> Any:
    """Best-effort conversion of nested objects to JSON-serializable types."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    # numpy arrays / scalars
    if hasattr(value, "tolist"):
        try:
            return _to_jsonable(value.tolist())
        except Exception:  # pragma: no cover
            return str(value)
    if hasattr(value, "shape"):
        return str(value)
    return str(value)


class EpisodeLogger:
    """Write one JSON file per task episode.

    Output shape::

        {
            "episode_id": str,
            "instruction": str,
            "timestamp_start": str,
            "timestamp_end": str,
            "success": bool,
            "steps": int,
            "scenario_key": str,
            "ltm_entries_used": list,
            "stm": [
                {
                    "step": int,
                    "action": dict,
                    "feedback": dict,
                    "planning_time_sec": float,
                    "execution_time_sec": float,
                    "detection_time_sec": float,
                }
            ],
            "experience_stored": str,
            "config_snapshot": dict
        }
    """

    def __init__(self, log_dir: Union[str, Path]) -> None:
        self.log_dir = Path(log_dir)
        ensure_dir(self.log_dir)
        self._open_episode: Optional[Dict[str, Any]] = None
        self._output_path: Optional[Path] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start_episode(self, instruction: str, cfg: DictConfig) -> str:
        episode_id = f"{_dt.datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        snapshot: Dict[str, Any]
        try:
            snapshot = OmegaConf.to_container(cfg, resolve=True)  # type: ignore[assignment]
        except Exception:
            snapshot = {}
        self._open_episode = {
            "episode_id": episode_id,
            "instruction": str(instruction),
            "timestamp_start": _now_iso(),
            "timestamp_end": "",
            "success": False,
            "steps": 0,
            "scenario_key": "",
            "ltm_entries_used": [],
            "stm": [],
            "experience_stored": "",
            "config_snapshot": _to_jsonable(snapshot),
        }
        self._output_path = self.log_dir / f"episode_{episode_id}.json"
        # Persist a partial file immediately so even a crash leaves something on disk.
        self._flush()
        return episode_id

    def log_step(
        self,
        step: int,
        action: Dict[str, Any],
        feedback: Dict[str, Any],
        timings: Optional[Dict[str, float]] = None,
    ) -> None:
        if self._open_episode is None:
            raise RuntimeError("log_step called without an active episode")
        timings = timings or {}
        entry = {
            "step": int(step),
            "action": _to_jsonable(action),
            "feedback": _to_jsonable(feedback),
            "planning_time_sec": float(timings.get("planning_time_sec", 0.0)),
            "execution_time_sec": float(timings.get("execution_time_sec", 0.0)),
            "detection_time_sec": float(timings.get("detection_time_sec", 0.0)),
        }
        self._open_episode["stm"].append(entry)
        self._open_episode["steps"] = len(self._open_episode["stm"])
        self._flush()

    def end_episode(
        self,
        success: bool,
        experience: str,
        scenario_key: str,
        ltm_entries_used: List[Dict[str, Any]],
        conversation: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        if self._open_episode is None or self._output_path is None:
            raise RuntimeError("end_episode called without an active episode")
        self._open_episode["success"] = bool(success)
        self._open_episode["experience_stored"] = str(experience or "")
        self._open_episode["scenario_key"] = str(scenario_key or "")
        self._open_episode["ltm_entries_used"] = _to_jsonable(ltm_entries_used or [])
        self._open_episode["timestamp_end"] = _now_iso()
        if conversation is not None:
            self._open_episode["conversation"] = _to_jsonable(conversation)
        path = str(self._output_path)
        self._flush()
        self._open_episode = None
        self._output_path = None
        return path

    # ------------------------------------------------------------------
    # IO
    # ------------------------------------------------------------------

    def _flush(self) -> None:
        if self._open_episode is None or self._output_path is None:
            return
        try:
            with open(self._output_path, "w", encoding="utf-8") as f:
                json.dump(self._open_episode, f, indent=2, default=str)
        except OSError as exc:  # pragma: no cover - disk failures
            logger.error("Failed to write episode log %s: %s", self._output_path, exc)

    @staticmethod
    def load_episode(path: Union[str, Path]) -> Dict[str, Any]:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
