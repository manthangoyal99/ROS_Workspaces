"""Read per-trial JSONs and emit paper-comparable CSVs / summary JSON."""

from __future__ import annotations

import csv
import datetime as _dt
import json
import logging as _stdlib_logging
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import numpy as np

from .task_suite import ALL_TASKS, TaskDefinition, get_table_tasks

logger = _stdlib_logging.getLogger(__name__)


class ResultAggregator:
    """Crunch trial JSONs into success-rate tables."""

    def __init__(self, results_dir: str) -> None:
        self.results_dir = Path(results_dir)
        self.trials_dir = self.results_dir / "trials"
        self.aggregate_dir = self.results_dir / "aggregate"
        self.aggregate_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load_trials(self) -> List[Dict[str, Any]]:
        if not self.trials_dir.exists():
            return []
        out: List[Dict[str, Any]] = []
        for path in sorted(self.trials_dir.glob("*.json")):
            try:
                with path.open("r", encoding="utf-8") as f:
                    out.append(json.load(f))
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Skipping unreadable trial %s: %s", path, exc)
        return out

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    @staticmethod
    def _filter(trials: Iterable[Dict[str, Any]], **predicate) -> List[Dict[str, Any]]:
        return [t for t in trials if all(t.get(k) == v for k, v in predicate.items())]

    def compute_task_stats(self, task_name: str, condition: str) -> Dict[str, Any]:
        trials = self._filter(self.load_trials(), task_name=task_name, condition=condition)
        n = len(trials)
        n_success = sum(1 for t in trials if t.get("success"))
        steps = [int(t.get("steps", 0)) for t in trials]
        durations = [float(t.get("duration_sec", 0.0)) for t in trials]
        planning = [float((t.get("per_step_timings") or {}).get("mean_planning_time_sec", 0.0)) for t in trials]
        execution = [float((t.get("per_step_timings") or {}).get("mean_execution_time_sec", 0.0)) for t in trials]
        crashes = sum(1 for t in trials if t.get("error"))

        success_rate = (n_success / n) if n else 0.0
        return {
            "task_name": task_name,
            "condition": condition,
            "n_trials": n,
            "n_success": n_success,
            "success_rate": float(success_rate),
            "success_rate_pct": float(round(success_rate * 100, 1)),
            "mean_steps": float(np.mean(steps) if steps else 0.0),
            "std_steps": float(np.std(steps) if steps else 0.0),
            "mean_duration_sec": float(np.mean(durations) if durations else 0.0),
            "mean_planning_time_sec": float(np.mean(planning) if planning else 0.0),
            "mean_execution_time_sec": float(np.mean(execution) if execution else 0.0),
            "crash_rate": float(crashes / n) if n else 0.0,
        }

    def compute_delta(
        self,
        task_name: str,
        baseline_condition: str,
        target_condition: str,
    ) -> Dict[str, float]:
        base = self.compute_task_stats(task_name, baseline_condition)
        tgt = self.compute_task_stats(task_name, target_condition)
        b = base["success_rate"]
        t = tgt["success_rate"]
        rel = (t - b) / b if b > 0 else float("nan")
        return {
            "delta_success_rate": float(t - b),
            "delta_success_rate_pct": float(round((t - b) * 100, 1)),
            "relative_improvement": float(rel),
        }

    # ------------------------------------------------------------------
    # CSV / JSON outputs
    # ------------------------------------------------------------------

    def _table_tasks(self, table: str) -> List[TaskDefinition]:
        return get_table_tasks(table)

    def _baseline_for(self, table: str) -> str:
        return "cap_v" if table == "table_2" else "come"

    def _table_paper_baseline_pct(self, task: TaskDefinition) -> float:
        return float(round(task.baseline_success_rate * 100, 1))

    def _table_paper_target_pct(self, task: TaskDefinition) -> float:
        return float(round(task.pragmabot_success_rate * 100, 1))

    def _generate_table_csv(self, table: str, output_path: Path) -> None:
        tasks = self._table_tasks(table)
        baseline = self._baseline_for(table)
        target = "pragmabot"

        rows: List[Dict[str, Any]] = []
        for task in tasks:
            b = self.compute_task_stats(task.name, baseline)
            t = self.compute_task_stats(task.name, target)
            rows.append({
                "task_name": task.name,
                f"{baseline}_pct": b["success_rate_pct"],
                f"{target}_pct": t["success_rate_pct"],
                "delta_pct": round(t["success_rate_pct"] - b["success_rate_pct"], 1),
                f"{baseline}_paper_pct": self._table_paper_baseline_pct(task),
                f"{target}_paper_pct": self._table_paper_target_pct(task),
                "n_trials_ours": t["n_trials"],
                "n_trials_paper": task.n_trials,
            })

        # MEAN row (over tasks where we have at least one trial of each condition).
        def _mean(col: str) -> float:
            values = [r[col] for r in rows if r["n_trials_ours"] > 0]
            return float(round(np.mean(values), 1)) if values else 0.0

        mean_row = {
            "task_name": "MEAN",
            f"{baseline}_pct": _mean(f"{baseline}_pct"),
            f"{target}_pct": _mean(f"{target}_pct"),
            "delta_pct": _mean("delta_pct"),
            f"{baseline}_paper_pct": _mean(f"{baseline}_paper_pct"),
            f"{target}_paper_pct": _mean(f"{target}_paper_pct"),
            "n_trials_ours": sum(r["n_trials_ours"] for r in rows),
            "n_trials_paper": sum(r["n_trials_paper"] for r in rows),
        }
        rows.append(mean_row)

        fieldnames = [
            "task_name",
            f"{baseline}_pct",
            f"{target}_pct",
            "delta_pct",
            f"{baseline}_paper_pct",
            f"{target}_paper_pct",
            "n_trials_ours",
            "n_trials_paper",
        ]
        with output_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def generate_table_2_csv(self, output_path: Optional[str] = None) -> Path:
        path = Path(output_path) if output_path else (self.aggregate_dir / "table_2_results.csv")
        self._generate_table_csv("table_2", path)
        return path

    def generate_table_3_csv(self, output_path: Optional[str] = None) -> Path:
        path = Path(output_path) if output_path else (self.aggregate_dir / "table_3_results.csv")
        self._generate_table_csv("table_3", path)
        return path

    def generate_full_results_csv(self, output_path: Optional[str] = None) -> Path:
        path = Path(output_path) if output_path else (self.aggregate_dir / "full_results.csv")
        trials = self.load_trials()
        pairs = sorted({(t.get("task_name", ""), t.get("condition", "")) for t in trials})
        rows = [self.compute_task_stats(task, cond) for task, cond in pairs]
        if not rows:
            path.write_text("", encoding="utf-8")
            return path
        fieldnames = list(rows[0].keys())
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        return path

    def generate_summary_json(self, output_path: Optional[str] = None) -> Path:
        path = Path(output_path) if output_path else (self.aggregate_dir / "summary.json")
        trials = self.load_trials()
        conditions = sorted({t.get("condition", "") for t in trials})
        tasks = sorted({t.get("task_name", "") for t in trials})

        by_condition: Dict[str, Dict[str, Any]] = {}
        for cond in conditions:
            rates = [
                self.compute_task_stats(task, cond)["success_rate"]
                for task in tasks if self.compute_task_stats(task, cond)["n_trials"] > 0
            ]
            by_condition[cond] = {
                "mean_success_rate": float(np.mean(rates)) if rates else 0.0,
                "tasks_above_paper": 0,
                "tasks_below_paper": 0,
            }

        # vs_paper deltas
        vs_paper: Dict[str, float] = {}
        for table in ("table_2", "table_3"):
            baseline = self._baseline_for(table)
            table_tasks = self._table_tasks(table)

            base_deltas: List[float] = []
            target_deltas: List[float] = []
            for task in table_tasks:
                ours_base = self.compute_task_stats(task.name, baseline)["success_rate"]
                ours_target = self.compute_task_stats(task.name, "pragmabot")["success_rate"]
                if ours_base or ours_target:
                    base_deltas.append(ours_base - task.baseline_success_rate)
                    target_deltas.append(ours_target - task.pragmabot_success_rate)
            if base_deltas:
                vs_paper[f"{table}_baseline_mean_delta"] = float(round(np.mean(base_deltas), 4))
            if target_deltas:
                vs_paper[f"{table}_pragmabot_mean_delta"] = float(round(np.mean(target_deltas), 4))

            # Above/below paper counts (only for pragmabot)
            for task in table_tasks:
                ours = self.compute_task_stats(task.name, "pragmabot")["success_rate"]
                if ours and "pragmabot" in by_condition:
                    if ours > task.pragmabot_success_rate:
                        by_condition["pragmabot"]["tasks_above_paper"] += 1
                    elif ours < task.pragmabot_success_rate:
                        by_condition["pragmabot"]["tasks_below_paper"] += 1

        payload = {
            "run_date": _dt.datetime.now().isoformat(timespec="seconds"),
            "n_tasks": len(tasks),
            "n_conditions": len(conditions),
            "n_total_trials": len(trials),
            "by_condition": by_condition,
            "vs_paper": vs_paper,
        }
        with path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, default=str)
        return path

    # ------------------------------------------------------------------
    # Pretty-print
    # ------------------------------------------------------------------

    def print_table(self, table: str) -> None:
        tasks = self._table_tasks(table)
        baseline = self._baseline_for(table)
        rows = []
        for task in tasks:
            b = self.compute_task_stats(task.name, baseline)
            t = self.compute_task_stats(task.name, "pragmabot")
            rows.append((
                task.name,
                f"{b['success_rate_pct']:.1f}%",
                f"{t['success_rate_pct']:.1f}%",
                f"{(t['success_rate_pct'] - b['success_rate_pct']):+.1f}%",
                f"{self._table_paper_baseline_pct(task):.1f}%",
                f"{self._table_paper_target_pct(task):.1f}%",
                str(t["n_trials"]),
            ))
        header = ("task", baseline, "pragmabot", "delta", f"{baseline} paper", "pragmabot paper", "n")
        widths = [max(len(str(r[i])) for r in (rows + [header])) for i in range(len(header))]
        line = "  ".join(str(v).ljust(widths[i]) for i, v in enumerate(header))
        print(line)
        print("-" * len(line))
        for row in rows:
            print("  ".join(str(v).ljust(widths[i]) for i, v in enumerate(row)))
