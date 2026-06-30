"""[MAC] Phase 6 smoke — run a stub evaluation, aggregate, print Table II."""

from __future__ import annotations

import json
import logging
import sys
import tempfile
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
    get_task,
)
from pragmabot.eval.conditions import ConditionManager  # noqa: E402
from pragmabot.pipeline import PragmaBot  # noqa: E402
from pragmabot.simple_config import load_config  # noqa: E402


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")

    tmp = Path(tempfile.mkdtemp(prefix="pragmabot_phase6_"))
    out_dir = tmp / "results"

    cfg = load_config(REPO_ROOT / "pragmabot" / "config" / "config.yaml")
    cfg.vlm.backend = "stub"
    cfg.embeddings.backend = "stub"
    cfg.perception.backend = "stub"
    cfg.robot.backend = "stub"
    cfg.memory.ltm_path = str(tmp / "ltm.csv")
    cfg.memory.embeddings_path = str(tmp / "ltm_embeddings.npy")
    cfg.logging.log_dir = str(out_dir / "episode_logs")
    cfg.pipeline.max_steps = 2
    cfg.vlm.detector_mode = "always_complete"

    pipeline = PragmaBot(cfg)
    runner = TrialRunner(pipeline, cfg, ConditionManager())

    task = get_task("apple_on_plate_container", table="table_2")
    eval_cfg = EvaluationConfig(
        conditions=["cap_v", "pragmabot"],
        tasks=[task],
        n_trials_override=3,
        output_dir=str(out_dir),
        resume=False,
    )
    evaluator = Evaluator(eval_cfg, runner)
    summary = evaluator.run()
    outputs = evaluator.aggregate()
    print("--- evaluator summary ---")
    print(json.dumps(summary, indent=2))

    agg = ResultAggregator(str(out_dir))
    print("--- Table II (partial: 1 task) ---")
    agg.print_table("table_2")

    csv_path = outputs["table_2_csv"]
    assert csv_path.exists(), f"missing {csv_path}"
    print(f"CSV path: {csv_path}")
    print(csv_path.read_text(encoding="utf-8"))

    report_path = ReportGenerator(agg).generate(str(out_dir / "report.md"))
    print(f"Report path: {report_path}")
    assert report_path.exists()

    # Print per-task delta vs paper (for the one task we actually ran).
    stats_target = agg.compute_task_stats(task.name, "pragmabot")
    stats_base = agg.compute_task_stats(task.name, "cap_v")
    paper_base_pct = task.baseline_success_rate * 100
    paper_target_pct = task.pragmabot_success_rate * 100
    print(
        f"Delta vs paper for {task.name}: "
        f"cap_v ours={stats_base['success_rate_pct']:.1f}% (paper {paper_base_pct:.1f}%), "
        f"pragmabot ours={stats_target['success_rate_pct']:.1f}% (paper {paper_target_pct:.1f}%)"
    )

    print("Phase 6 Mac smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
