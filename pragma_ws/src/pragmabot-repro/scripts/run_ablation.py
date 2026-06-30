"""Run an ablation study — sweep one or more config keys.

Usage:
    python scripts/run_ablation.py --sweep memory.top_k 1 3 5 \\
        --tasks table_2 --n_trials 3 --output_dir results/ablation_top_k --stub

    python scripts/run_ablation.py --sweep memory.top_k 1 3 5 \\
        --sweep vlm.temperature 0.0 0.3 \\
        --tasks table_2 --n_trials 3 --output_dir results/ablation_multi --stub
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PKG_SRC = REPO_ROOT / "pragmabot" / "src"
if str(PKG_SRC) not in sys.path:
    sys.path.insert(0, str(PKG_SRC))

from pragmabot.ablation import AblationConfigBuilder, AblationRunner  # noqa: E402
from pragmabot.eval import get_table_tasks, get_task  # noqa: E402


def _parse_value(v: str):
    """Coerce CLI strings into the most natural Python type."""
    if v.lower() in ("true", "false"):
        return v.lower() == "true"
    for caster in (int, float):
        try:
            return caster(v)
        except ValueError:
            pass
    return v


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument(
        "--sweep", action="append", nargs="+", required=True,
        metavar=("KEY", "VAL"),
        help="Repeatable: --sweep memory.top_k 1 3 5",
    )
    p.add_argument("--tasks", choices=["table_2", "table_3"], default="table_2")
    p.add_argument("--task", default=None, help="single task to evaluate (overrides --tasks)")
    p.add_argument("--conditions", nargs="+", default=["pragmabot"])
    p.add_argument("--n_trials", type=int, default=3)
    p.add_argument("--output_dir", required=True)
    p.add_argument("--config_path", default=None)
    p.add_argument("--stub", action="store_true")
    return p.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")
    args = parse_args()

    cfg_path = args.config_path or str(REPO_ROOT / "pragmabot" / "config" / "config.yaml")
    builder = AblationConfigBuilder(cfg_path)

    if args.stub:
        for k, v in (
            ("vlm.backend", "stub"),
            ("embeddings.backend", "stub"),
            ("perception.backend", "stub"),
            ("robot.backend", "stub"),
            ("vlm.detector_mode", "always_complete"),
        ):
            builder.fix(k, v)

    for sweep_spec in args.sweep:
        if len(sweep_spec) < 2:
            raise SystemExit(f"--sweep expects KEY V1 [V2 ...], got {sweep_spec!r}")
        key, *values = sweep_spec
        builder.sweep(key, [_parse_value(v) for v in values])

    if args.task:
        tasks = [get_task(args.task)]
    else:
        tasks = get_table_tasks(args.tasks)

    runner = AblationRunner(
        config_builder=builder,
        tasks=tasks,
        n_trials=int(args.n_trials),
        conditions=list(args.conditions),
    )
    results = runner.run(args.output_dir)
    runner.summarize(results)
    csv_path = runner.generate_comparison_csv(results, str(Path(args.output_dir) / "comparison.csv"))
    print(f"Comparison CSV: {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
