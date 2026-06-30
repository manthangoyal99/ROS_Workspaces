"""One-trial runner — wraps a single ``PragmaBot.run_task`` call with safety."""

from __future__ import annotations

import datetime as _dt
import json
import logging as _stdlib_logging
import time
import traceback
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

from omegaconf import DictConfig

from .conditions import ConditionManager

if TYPE_CHECKING:  # pragma: no cover
    from ..pipeline import PragmaBot

logger = _stdlib_logging.getLogger(__name__)


@dataclass
class TrialConfig:
    task_name: str
    instruction: str
    trial_id: int
    condition: str
    use_stm: bool
    use_ltm: bool
    max_steps: int = 10
    timeout_sec: float = 120.0
    scene_reset_fn: Optional[Callable[[], None]] = None
    paper_table: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d.pop("scene_reset_fn", None)
        return d


@dataclass
class TrialResult:
    trial_config: TrialConfig
    success: bool
    steps: int
    duration_sec: float
    episode_log_path: str
    failure_reason: Optional[str]
    stm_entries: List[Dict[str, Any]] = field(default_factory=list)
    ltm_entries_used: List[Dict[str, Any]] = field(default_factory=list)
    per_step_timings: Dict[str, float] = field(default_factory=dict)
    error: Optional[str] = None
    timestamp: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trial_config": self.trial_config.to_dict(),
            "trial_id": self.trial_config.trial_id,
            "task_name": self.trial_config.task_name,
            "condition": self.trial_config.condition,
            "instruction": self.trial_config.instruction,
            "success": bool(self.success),
            "steps": int(self.steps),
            "duration_sec": float(self.duration_sec),
            "failure_reason": self.failure_reason,
            "error": self.error,
            "stm_entries": self.stm_entries,
            "ltm_entries_used": self.ltm_entries_used,
            "per_step_timings": self.per_step_timings,
            "episode_log_path": self.episode_log_path,
            "timestamp": self.timestamp,
        }


class TrialRunner:
    """Run a single trial, applying the condition manager safely."""

    def __init__(
        self,
        pipeline: "PragmaBot",
        cfg: DictConfig,
        condition_manager: Optional[ConditionManager] = None,
    ) -> None:
        self.pipeline = pipeline
        self.cfg = cfg
        self.condition_manager = condition_manager or ConditionManager()

    def _aggregate_timings(self, stm_entries: List[Dict[str, Any]]) -> Dict[str, float]:
        keys = ("planning_time_sec", "execution_time_sec",
                "detection_time_sec", "perception_time_sec")
        sums = {k: 0.0 for k in keys}
        counts = {k: 0 for k in keys}
        for entry in stm_entries:
            timings = (entry.get("feedback") or {}).get("_timings") or {}
            for k in keys:
                if k in timings:
                    sums[k] += float(timings[k])
                    counts[k] += 1
        return {
            f"mean_{k.replace('_sec', '')}_sec": (sums[k] / counts[k]) if counts[k] else 0.0
            for k in keys
        }

    def run(self, trial_cfg: TrialConfig) -> TrialResult:
        timestamp = _dt.datetime.now().isoformat(timespec="seconds")
        t0 = time.perf_counter()
        result_dict: Dict[str, Any] = {}
        error: Optional[str] = None
        failure_reason: Optional[str] = None

        # Best-effort: scene reset before each trial.
        if trial_cfg.scene_reset_fn is not None:
            try:
                trial_cfg.scene_reset_fn()
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("scene_reset_fn raised: %s", exc)

        # Apply max_steps override on the pipeline for the duration of this trial.
        prev_max_steps = self.pipeline.max_steps
        self.pipeline.max_steps = int(trial_cfg.max_steps)

        try:
            with self.condition_manager.apply(trial_cfg.condition, self.pipeline):
                result_dict = self.pipeline.run_task(trial_cfg.instruction)
        except Exception as exc:  # pragma: no cover - pipeline already catches
            error = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
            logger.error("Trial crashed: %s", error)
            result_dict = {}
        finally:
            self.pipeline.max_steps = prev_max_steps

        duration = time.perf_counter() - t0
        if not result_dict.get("success", False) and not error:
            failure_reason = result_dict.get("error") or "task did not reach task_complete"
            failure_reason = failure_reason or None

        return TrialResult(
            trial_config=trial_cfg,
            success=bool(result_dict.get("success", False)),
            steps=int(result_dict.get("steps", 0)),
            duration_sec=float(duration),
            episode_log_path=str(result_dict.get("episode_log_path", "") or ""),
            failure_reason=failure_reason,
            stm_entries=list(result_dict.get("stm", [])),
            ltm_entries_used=list(result_dict.get("ltm_entries_used", [])),
            per_step_timings=self._aggregate_timings(list(result_dict.get("stm", []))),
            error=error,
            timestamp=timestamp,
        )


def save_trial_result(result: TrialResult, output_dir: Path) -> Path:
    """Write a TrialResult to ``output_dir/{task}_{condition}_{trial_id}.json``."""
    output_dir.mkdir(parents=True, exist_ok=True)
    fname = (
        f"{result.trial_config.task_name}_"
        f"{result.trial_config.condition}_"
        f"trial{result.trial_config.trial_id:02d}.json"
    )
    path = output_dir / fname
    with path.open("w", encoding="utf-8") as f:
        json.dump(result.to_dict(), f, indent=2, default=str)
    return path


def trial_result_path(output_dir: Path, task_name: str, condition: str, trial_id: int) -> Path:
    return output_dir / f"{task_name}_{condition}_trial{trial_id:02d}.json"
