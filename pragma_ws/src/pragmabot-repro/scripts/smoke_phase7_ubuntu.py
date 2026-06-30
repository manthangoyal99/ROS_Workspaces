"""[UBUNTU] Phase 7 smoke — franka_ros registry + 2-condition partial Table II."""

from __future__ import annotations

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
    ResultAggregator,
    TrialRunner,
    get_task,
)
from pragmabot.eval.conditions import ConditionManager  # noqa: E402
from pragmabot.pipeline import PragmaBot  # noqa: E402
from pragmabot.registry import registry  # noqa: E402
from pragmabot.simple_config import load_config  # noqa: E402
from pragmabot.utils.reproducibility import assert_backends_available  # noqa: E402


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    rospy.init_node("pragmabot_phase7_ubuntu_smoke", anonymous=True, disable_signals=True)

    tmp = Path(tempfile.mkdtemp(prefix="pragmabot_phase7_ubuntu_"))

    cfg = load_config(REPO_ROOT / "pragmabot" / "config" / "config.yaml")
    cfg.vlm.backend = "stub"
    cfg.embeddings.backend = "stub"
    cfg.perception.backend = "stub"
    cfg.robot.backend = "franka_ros"
    cfg.memory.ltm_path = str(tmp / "ltm.csv")
    cfg.memory.embeddings_path = str(tmp / "ltm.npy")
    cfg.logging.log_dir = str(tmp / "logs")
    cfg.pipeline.max_steps = 1
    cfg.vlm.detector_mode = "always_complete"

    assert_backends_available(cfg)
    assert "franka_ros" in registry.list_available("robot"), \
        "franka_ros not registered — is MoveIt installed?"

    pipeline = PragmaBot(cfg)
    runner = TrialRunner(pipeline, cfg, ConditionManager())
    task = get_task("apple_on_plate_container", table="table_2")
    eval_cfg = EvaluationConfig(
        conditions=["cap_v", "pragmabot"],
        tasks=[task],
        n_trials_override=1,
        output_dir=str(tmp / "results"),
        resume=False,
    )
    summary = Evaluator(eval_cfg, runner).run()
    print(summary)

    agg = ResultAggregator(str(tmp / "results"))
    agg.generate_table_2_csv()
    agg.print_table("table_2")
    print("Phase 7 Ubuntu smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
