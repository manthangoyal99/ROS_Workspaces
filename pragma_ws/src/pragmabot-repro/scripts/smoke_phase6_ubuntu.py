"""[UBUNTU] Phase 6 smoke — 2 trials × 2 tasks with the real Gazebo Franka."""

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

try:
    import rospy  # type: ignore
except ImportError:
    print("ROS not available — this smoke script must run on Ubuntu with ROS Noetic.")
    sys.exit(2)

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
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    rospy.init_node("pragmabot_phase6_ubuntu_smoke", anonymous=True, disable_signals=True)

    tmp = Path(tempfile.mkdtemp(prefix="pragmabot_phase6_ubuntu_"))
    out_dir = tmp / "results"

    cfg = load_config(REPO_ROOT / "pragmabot" / "config" / "config.yaml")
    cfg.vlm.backend = "stub"
    cfg.embeddings.backend = "stub"
    cfg.perception.backend = "stub"
    cfg.robot.backend = "franka_ros"
    cfg.memory.ltm_path = str(tmp / "ltm.csv")
    cfg.memory.embeddings_path = str(tmp / "ltm_embeddings.npy")
    cfg.logging.log_dir = str(out_dir / "episode_logs")
    cfg.pipeline.max_steps = 1
    cfg.vlm.detector_mode = "always_complete"

    pipeline = PragmaBot(cfg)
    runner = TrialRunner(pipeline, cfg, ConditionManager())

    tasks = [
        get_task("apple_on_plate_container", table="table_2"),
        get_task("egg_move_open", table="table_2"),
    ]
    eval_cfg = EvaluationConfig(
        conditions=["pragmabot"],
        tasks=tasks,
        n_trials_override=2,
        output_dir=str(out_dir),
        resume=False,
    )
    summary = Evaluator(eval_cfg, runner).run()
    print(json.dumps(summary, indent=2))

    agg = ResultAggregator(str(out_dir))
    agg.generate_table_2_csv()
    agg.generate_summary_json()
    agg.print_table("table_2")
    ReportGenerator(agg).generate(str(out_dir / "report.md"))

    print("Phase 6 Ubuntu smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
