"""Ablation runner — drive the evaluator across a sweep of configs."""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from omegaconf import DictConfig

from ..eval import (
    EvaluationConfig,
    Evaluator,
    ResultAggregator,
    TaskDefinition,
    TrialRunner,
)
from ..eval.conditions import ConditionManager
from ..pipeline import PragmaBot
from .config_builder import AblationConfigBuilder

logger = logging.getLogger(__name__)


class AblationRunner:
    """Run an evaluator under every config produced by an ``AblationConfigBuilder``."""

    def __init__(
        self,
        config_builder: AblationConfigBuilder,
        tasks: List[TaskDefinition],
        n_trials: int,
        conditions: Optional[List[str]] = None,
    ) -> None:
        self.config_builder = config_builder
        self.tasks = list(tasks)
        self.n_trials = int(n_trials)
        self.conditions = list(conditions or ["pragmabot"])

    # ------------------------------------------------------------------

    def run(self, output_dir: str) -> Dict[str, Dict[str, Any]]:
        results: Dict[str, Dict[str, Any]] = {}
        out_root = Path(output_dir)
        out_root.mkdir(parents=True, exist_ok=True)

        for run_name, cfg in self.config_builder.build():
            run_dir = out_root / run_name
            run_dir.mkdir(parents=True, exist_ok=True)

            # Ablation overrides episode log path so each run is self-contained.
            cfg.logging.log_dir = str(run_dir / "episode_logs")

            pipeline = PragmaBot(cfg)
            runner = TrialRunner(pipeline, cfg, ConditionManager())
            eval_cfg = EvaluationConfig(
                conditions=list(self.conditions),
                tasks=list(self.tasks),
                n_trials_override=self.n_trials,
                output_dir=str(run_dir),
                resume=True,
            )
            summary = Evaluator(eval_cfg, runner).run()
            agg = ResultAggregator(str(run_dir))
            agg.generate_table_2_csv()
            agg.generate_table_3_csv()
            agg.generate_full_results_csv()
            agg.generate_summary_json()

            results[run_name] = {
                "summary": summary,
                "run_dir": str(run_dir),
                "by_condition": self._mean_success_by_condition(agg),
                "config": cfg,
            }
        return results

    # ------------------------------------------------------------------

    def _mean_success_by_condition(self, agg: ResultAggregator) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for cond in self.conditions:
            rates = []
            for task in self.tasks:
                stats = agg.compute_task_stats(task.name, cond)
                if stats["n_trials"] > 0:
                    rates.append(stats["success_rate"])
            out[cond] = float(sum(rates) / len(rates)) if rates else 0.0
        return out

    def summarize(self, results: Dict[str, Dict[str, Any]]) -> None:
        if not results:
            print("(no ablation results)")
            return
        first_name = next(iter(results))
        base_mean = list(results[first_name]["by_condition"].values())[0] if results[first_name]["by_condition"] else 0.0
        header = ("run_name", "mean_success_rate", "delta_vs_first")
        rows = []
        for name, payload in results.items():
            vals = list(payload["by_condition"].values()) or [0.0]
            mean = float(sum(vals) / len(vals))
            rows.append((name, f"{mean:.3f}", f"{(mean - base_mean):+.3f}"))
        widths = [max(len(r[i]) for r in rows + [header]) for i in range(3)]
        print("  ".join(h.ljust(widths[i]) for i, h in enumerate(header)))
        print("-" * (sum(widths) + 4))
        for row in rows:
            print("  ".join(row[i].ljust(widths[i]) for i in range(3)))

    def generate_comparison_csv(
        self,
        results: Dict[str, Dict[str, Any]],
        output_path: str,
    ) -> Path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        # One row per (run_name, condition).
        rows: List[Dict[str, Any]] = []
        for run_name, payload in results.items():
            for cond, rate in payload["by_condition"].items():
                rows.append({
                    "run_name": run_name,
                    "condition": cond,
                    "mean_success_rate": round(float(rate), 4),
                    "n_tasks": len(self.tasks),
                    "n_trials_per_task": self.n_trials,
                })
        fieldnames = ["run_name", "condition", "mean_success_rate", "n_tasks", "n_trials_per_task"]
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        return path
