"""Multi-trial evaluator — orchestrates TrialRunner across tasks × conditions."""

from __future__ import annotations

import logging as _stdlib_logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .aggregator import ResultAggregator
from .conditions import CONDITIONS
from .task_suite import TaskDefinition
from .trial_runner import (
    TrialConfig,
    TrialResult,
    TrialRunner,
    save_trial_result,
    trial_result_path,
)

logger = _stdlib_logging.getLogger(__name__)


@dataclass
class EvaluationConfig:
    conditions: List[str]
    tasks: List[TaskDefinition]
    output_dir: str
    n_trials_override: Optional[int] = None
    resume: bool = True
    timeout_sec: float = 120.0
    max_steps: int = 10


class Evaluator:
    """Drive the full grid of (task × condition × trial_id)."""

    def __init__(self, eval_cfg: EvaluationConfig, trial_runner: TrialRunner) -> None:
        self.eval_cfg = eval_cfg
        self.trial_runner = trial_runner
        self.output_dir = Path(eval_cfg.output_dir)
        self.trials_dir = self.output_dir / "trials"
        self.trials_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------

    def _n_trials_for(self, task: TaskDefinition) -> int:
        if self.eval_cfg.n_trials_override is not None:
            return int(self.eval_cfg.n_trials_override)
        return int(task.n_trials)

    def _should_skip(self, task: TaskDefinition, condition: str, trial_id: int) -> bool:
        if not self.eval_cfg.resume:
            return False
        return trial_result_path(self.trials_dir, task.name, condition, trial_id).exists()

    # ------------------------------------------------------------------

    def run(self) -> Dict[str, Any]:
        completed: List[TrialResult] = []
        skipped = 0
        total = sum(
            len(self.eval_cfg.conditions) * self._n_trials_for(t)
            for t in self.eval_cfg.tasks
        )
        done = 0

        for t_idx, task in enumerate(self.eval_cfg.tasks, start=1):
            n_trials = self._n_trials_for(task)
            for cond_idx, condition in enumerate(self.eval_cfg.conditions, start=1):
                if condition not in CONDITIONS:
                    raise KeyError(f"unknown condition {condition!r}")
                for trial_id in range(n_trials):
                    done += 1
                    print(
                        f"[{done}/{total}] task {t_idx}/{len(self.eval_cfg.tasks)} "
                        f"({task.name}) condition {cond_idx}/{len(self.eval_cfg.conditions)} "
                        f"({condition}) trial {trial_id + 1}/{n_trials}"
                    )
                    if self._should_skip(task, condition, trial_id):
                        skipped += 1
                        continue

                    cond_cfg = CONDITIONS[condition]
                    trial_cfg = TrialConfig(
                        task_name=task.name,
                        instruction=task.instruction,
                        trial_id=trial_id,
                        condition=condition,
                        use_stm=bool(cond_cfg["use_stm"]),
                        use_ltm=bool(cond_cfg["use_ltm"]),
                        max_steps=self.eval_cfg.max_steps,
                        timeout_sec=self.eval_cfg.timeout_sec,
                        paper_table=task.paper_table,
                    )
                    result = self.trial_runner.run(trial_cfg)
                    save_trial_result(result, self.trials_dir)
                    completed.append(result)

        summary = {
            "n_completed": len(completed),
            "n_skipped": skipped,
            "n_total": total,
            "successes": sum(1 for r in completed if r.success),
            "failures": sum(1 for r in completed if not r.success and not r.error),
            "crashes": sum(1 for r in completed if r.error),
        }
        return summary

    def aggregate(self) -> Dict[str, Path]:
        agg = ResultAggregator(str(self.output_dir))
        return {
            "table_2_csv": agg.generate_table_2_csv(),
            "table_3_csv": agg.generate_table_3_csv(),
            "full_csv": agg.generate_full_results_csv(),
            "summary_json": agg.generate_summary_json(),
        }
