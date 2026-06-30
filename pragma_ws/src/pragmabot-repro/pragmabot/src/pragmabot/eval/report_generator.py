"""Markdown report generator for evaluation runs."""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import Dict, List, Optional

from .aggregator import ResultAggregator
from .task_suite import TaskDefinition, get_table_tasks


class ReportGenerator:
    """Produce a structured markdown report from a ResultAggregator."""

    def __init__(self, aggregator: ResultAggregator) -> None:
        self.aggregator = aggregator

    def _comparison_table(self, table: str) -> str:
        tasks: List[TaskDefinition] = get_table_tasks(table)
        baseline = "cap_v" if table == "table_2" else "come"
        lines = [
            f"| Task | Baseline (paper) | PragmaBot (paper) | Baseline (ours) | PragmaBot (ours) | Δ vs paper (PragmaBot) | n ours / paper |",
            "|---|---|---|---|---|---|---|",
        ]
        for task in tasks:
            ours_base = self.aggregator.compute_task_stats(task.name, baseline)
            ours_target = self.aggregator.compute_task_stats(task.name, "pragmabot")
            paper_base_pct = task.baseline_success_rate * 100
            paper_tgt_pct = task.pragmabot_success_rate * 100
            delta_target = ours_target["success_rate_pct"] - paper_tgt_pct
            lines.append(
                f"| {task.name} | {paper_base_pct:.1f}% | {paper_tgt_pct:.1f}% | "
                f"{ours_base['success_rate_pct']:.1f}% | {ours_target['success_rate_pct']:.1f}% | "
                f"{delta_target:+.1f}% | {ours_target['n_trials']}/{task.n_trials} |"
            )
        return "\n".join(lines)

    def _note_small_n(self, table: str) -> Optional[str]:
        tasks = get_table_tasks(table)
        warnings = []
        for task in tasks:
            ours = self.aggregator.compute_task_stats(task.name, "pragmabot")
            if ours["n_trials"] > 0 and ours["n_trials"] < task.n_trials:
                warnings.append(
                    f"- `{task.name}`: only {ours['n_trials']} trials run "
                    f"(paper uses {task.n_trials})."
                )
        if not warnings:
            return None
        return "**Note — trials below paper n:**\n" + "\n".join(warnings)

    def _failure_patterns(self) -> str:
        trials = self.aggregator.load_trials()
        if not trials:
            return "_No trials found._"
        from collections import Counter

        counter: Counter = Counter()
        for trial in trials:
            if trial.get("success"):
                continue
            reason = trial.get("failure_reason") or trial.get("error") or "unknown"
            counter[str(reason)[:120]] += 1
        if not counter:
            return "_No failures recorded._"
        lines = []
        for reason, count in counter.most_common(10):
            lines.append(f"- ({count}×) {reason}")
        return "\n".join(lines)

    def _timing_section(self) -> str:
        trials = self.aggregator.load_trials()
        if not trials:
            return "_No trials found._"
        keys = ("mean_planning_time_sec", "mean_execution_time_sec",
                "mean_detection_time_sec", "mean_perception_time_sec")
        from statistics import mean

        all_values: Dict[str, list] = {k: [] for k in keys}
        for t in trials:
            timings = t.get("per_step_timings") or {}
            for k in keys:
                if k in timings:
                    all_values[k].append(float(timings[k]))
        lines = ["| Step | Mean (sec) | N samples |", "|---|---|---|"]
        for k in keys:
            vs = all_values[k]
            if not vs:
                lines.append(f"| {k} | — | 0 |")
            else:
                lines.append(f"| {k} | {mean(vs):.4f} | {len(vs)} |")
        return "\n".join(lines)

    # ------------------------------------------------------------------

    def generate(self, output_path: str) -> Path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        trials = self.aggregator.load_trials()
        conditions = sorted({t.get("condition", "") for t in trials})
        tasks_run = sorted({t.get("task_name", "") for t in trials})

        sections: List[str] = []
        sections.append(f"# PragmaBot evaluation report\n")
        sections.append(f"_Generated: {_dt.datetime.now().isoformat(timespec='seconds')}_\n")
        sections.append("## Run metadata\n")
        sections.append(
            "\n".join([
                f"- Results dir: `{self.aggregator.results_dir}`",
                f"- Trials on disk: {len(trials)}",
                f"- Tasks seen: {len(tasks_run)}",
                f"- Conditions seen: {', '.join(conditions) or '(none)'}",
            ]) + "\n"
        )

        # Table II
        table2_trials = [t for t in trials if t.get("task_name") in {x.name for x in get_table_tasks("table_2")}]
        if table2_trials:
            sections.append("## Table II reproduction (STM effect)\n")
            sections.append(self._comparison_table("table_2") + "\n")
            note = self._note_small_n("table_2")
            if note:
                sections.append(note + "\n")

        # Table III
        table3_trials = [t for t in trials if t.get("task_name") in {x.name for x in get_table_tasks("table_3")}]
        if table3_trials:
            sections.append("## Table III reproduction (LTM/RAG effect)\n")
            sections.append(self._comparison_table("table_3") + "\n")
            note = self._note_small_n("table_3")
            if note:
                sections.append(note + "\n")

        sections.append("## Failure patterns\n")
        sections.append(self._failure_patterns() + "\n")

        sections.append("## Timing statistics\n")
        sections.append(self._timing_section() + "\n")

        # Summary JSON dump
        summary_path = self.aggregator.aggregate_dir / "summary.json"
        if summary_path.exists():
            try:
                with summary_path.open("r", encoding="utf-8") as f:
                    summary = json.load(f)
                sections.append("## Summary JSON\n```json\n" + json.dumps(summary, indent=2) + "\n```\n")
            except (OSError, json.JSONDecodeError):
                pass

        sections.append(
            "## Limitations and notes\n"
            "- Stub backends produce trivially low timings; real-VLM numbers will look very different.\n"
            "- Trials below the paper's `n_trials` are noted above and reduce statistical confidence.\n"
        )

        out.write_text("\n".join(sections), encoding="utf-8")
        return out
