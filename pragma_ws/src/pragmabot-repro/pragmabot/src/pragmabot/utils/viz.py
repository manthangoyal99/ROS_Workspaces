"""Matplotlib visualizations for evaluation results and pipeline debugging."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import numpy as np

PathLike = Union[str, Path]


def _setup_matplotlib():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # noqa: WPS433

    return plt


def plot_success_rates(
    results: Dict[str, Dict[str, float]],
    output_path: PathLike,
    title: str = "Success Rates by Task and Condition",
    paper_targets: Optional[Dict[str, Dict[str, float]]] = None,
) -> Path:
    """Bar chart: one group per task, one bar per condition.

    Args:
        results: ``{task_name: {condition: success_rate}}`` in [0, 1].
        output_path: where to save the PNG.
        paper_targets: optional ``{task_name: {condition: rate}}`` reference
            values rendered as horizontal markers.
    """
    plt = _setup_matplotlib()

    tasks = list(results.keys())
    conditions = sorted({c for d in results.values() for c in d.keys()})
    x = np.arange(len(tasks))
    width = 0.8 / max(len(conditions), 1)

    fig, ax = plt.subplots(figsize=(max(6, len(tasks) * 1.2), 4.5))
    for i, cond in enumerate(conditions):
        rates = [results[t].get(cond, 0.0) for t in tasks]
        offset = (i - (len(conditions) - 1) / 2) * width
        ax.bar(x + offset, rates, width=width * 0.9, label=cond)

    if paper_targets:
        for i, cond in enumerate(conditions):
            offset = (i - (len(conditions) - 1) / 2) * width
            for ti, task in enumerate(tasks):
                target = paper_targets.get(task, {}).get(cond)
                if target is None:
                    continue
                ax.plot(
                    [x[ti] + offset - width / 2, x[ti] + offset + width / 2],
                    [target, target],
                    color="black", linestyle="--", linewidth=1.0,
                )

    ax.set_xticks(x)
    ax.set_xticklabels(tasks, rotation=30, ha="right")
    ax.set_ylim(0.0, 1.05)
    ax.set_ylabel("Success rate")
    ax.set_title(title)
    ax.legend(loc="upper right")
    fig.tight_layout()
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return out


def plot_stm_length_vs_success(
    trial_results: List[Dict[str, Any]],
    output_path: PathLike,
) -> Path:
    plt = _setup_matplotlib()
    succ_steps = [t.get("steps", 0) for t in trial_results if t.get("success")]
    fail_steps = [t.get("steps", 0) for t in trial_results if not t.get("success")]

    fig, ax = plt.subplots(figsize=(6, 4))
    if succ_steps:
        ax.hist(succ_steps, bins=range(1, max(succ_steps + [1]) + 2),
                alpha=0.6, label="success")
    if fail_steps:
        ax.hist(fail_steps, bins=range(1, max(fail_steps + [1]) + 2),
                alpha=0.6, label="failure")
    ax.set_xlabel("Steps")
    ax.set_ylabel("Trials")
    ax.set_title("Steps to outcome")
    ax.legend()
    fig.tight_layout()
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return out


def plot_ltm_retrieval_heatmap(
    memory_manager,
    output_path: PathLike,
) -> Path:
    plt = _setup_matplotlib()
    emb = getattr(memory_manager, "_embeddings", None)
    n = len(memory_manager) if hasattr(memory_manager, "__len__") else 0
    if emb is None or n == 0:
        sim = np.zeros((1, 1))
    else:
        norms = np.linalg.norm(emb, axis=1, keepdims=True)
        norms = np.where(norms == 0.0, 1.0, norms)
        normed = emb / norms
        sim = normed @ normed.T

    fig, ax = plt.subplots(figsize=(5, 4))
    im = ax.imshow(sim, vmin=-1.0, vmax=1.0, cmap="viridis")
    ax.set_title(f"LTM cosine similarity (n={n})")
    fig.colorbar(im, ax=ax)
    fig.tight_layout()
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return out


def plot_timing_breakdown(
    trial_results: List[Dict[str, Any]],
    output_path: PathLike,
) -> Path:
    plt = _setup_matplotlib()
    labels = [t.get("task_name", str(i)) for i, t in enumerate(trial_results)]
    planning = [float((t.get("per_step_timings") or {}).get("mean_planning_time_sec", 0.0))
                for t in trial_results]
    execution = [float((t.get("per_step_timings") or {}).get("mean_execution_time_sec", 0.0))
                 for t in trial_results]
    detection = [float((t.get("per_step_timings") or {}).get("mean_detection_time_sec", 0.0))
                 for t in trial_results]

    x = np.arange(len(labels))
    fig, ax = plt.subplots(figsize=(max(6, len(labels) * 0.8), 4.5))
    ax.bar(x, planning, label="planning")
    ax.bar(x, execution, bottom=planning, label="execution")
    bottom2 = [p + e for p, e in zip(planning, execution)]
    ax.bar(x, detection, bottom=bottom2, label="detection")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=30, ha="right")
    ax.set_ylabel("Time (s) per step")
    ax.set_title("Per-step timing breakdown")
    ax.legend()
    fig.tight_layout()
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return out
