"""Run PragmaBot evaluation across tasks × conditions.

Usage:
    python scripts/run_evaluation.py --table table_2 \\
        --conditions cap_v pragmabot --n_trials 5 \\
        --output_dir results/table_2_stub --stub

    python scripts/run_evaluation.py --task apple_on_plate_container \\
        --conditions pragmabot --n_trials 2 --output_dir results/debug --stub

    python scripts/run_evaluation.py --aggregate_only \\
        --output_dir results/table_2_stub --table table_2
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PKG_SRC = REPO_ROOT / "pragmabot" / "src"
if str(PKG_SRC) not in sys.path:
    sys.path.insert(0, str(PKG_SRC))

from pragmabot.eval import (  # noqa: E402
    EvaluationConfig,
    Evaluator,
    ReportGenerator,
    ResultAggregator,
    TrialRunner,
    get_table_tasks,
    get_task,
)
from pragmabot.eval.conditions import ConditionManager  # noqa: E402
from pragmabot.pipeline import PragmaBot  # noqa: E402
from pragmabot.simple_config import load_config  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--table", choices=["table_2", "table_3"], default=None)
    p.add_argument("--task", default=None, help="single task name (mutually exclusive with --table)")
    p.add_argument("--conditions", nargs="+", default=["cap_v", "pragmabot"])
    p.add_argument("--n_trials", type=int, default=None, help="override task.n_trials")
    p.add_argument("--max_steps", type=int, default=10)
    p.add_argument("--output_dir", required=True)
    p.add_argument("--config_path", default=None)
    p.add_argument("--stub", action="store_true", help="force all backends to stub (Mac-safe)")
    p.add_argument("--no_resume", action="store_true")
    p.add_argument("--aggregate_only", action="store_true",
                   help="skip trials, just aggregate existing results")
    return p.parse_args()


def build_pipeline(args: argparse.Namespace):
    cfg_path = args.config_path or str(REPO_ROOT / "pragmabot" / "config" / "config.yaml")
    cfg = load_config(cfg_path)
    if args.stub:
        cfg.vlm.backend = "stub"
        cfg.embeddings.backend = "stub"
        cfg.perception.backend = "stub"
        cfg.robot.backend = "stub"
        cfg.vlm.detector_mode = "always_complete"
    # Episode logs land alongside the trial JSONs.
    cfg.logging.log_dir = str(Path(args.output_dir) / "episode_logs")
    cfg.pipeline.max_steps = int(args.max_steps)
    return cfg, PragmaBot(cfg)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    args = parse_args()

    if args.aggregate_only:
        agg = ResultAggregator(args.output_dir)
        if args.table:
            agg.print_table(args.table)
        agg.generate_table_2_csv()
        agg.generate_table_3_csv()
        agg.generate_full_results_csv()
        agg.generate_summary_json()
        ReportGenerator(agg).generate(str(Path(args.output_dir) / "report.md"))
        return 0

    if args.table and args.task:
        raise SystemExit("Use --table or --task, not both.")

    tasks = []
    if args.table:
        tasks = get_table_tasks(args.table)
    elif args.task:
        tasks = [get_task(args.task)]
    else:
        raise SystemExit("--table or --task is required (or use --aggregate_only).")

    cfg, pipeline = build_pipeline(args)
    runner = TrialRunner(pipeline, cfg, ConditionManager())

    eval_cfg = EvaluationConfig(
        conditions=list(args.conditions),
        tasks=list(tasks),
        n_trials_override=args.n_trials,
        output_dir=args.output_dir,
        resume=not args.no_resume,
        max_steps=int(args.max_steps),
    )
    evaluator = Evaluator(eval_cfg, runner)
    summary = evaluator.run()
    outputs = evaluator.aggregate()
    print(json.dumps(summary, indent=2))
    print("Generated:")
    for k, v in outputs.items():
        print(f"  {k}: {v}")

    agg = ResultAggregator(args.output_dir)
    if args.table:
        agg.print_table(args.table)
    ReportGenerator(agg).generate(str(Path(args.output_dir) / "report.md"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
