"""[MAC] Phase 4 smoke — grasp synthesis + stub robot + Franka guard message."""

from __future__ import annotations

import json
import logging
import sys
import tempfile
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
PKG_SRC = REPO_ROOT / "pragmabot" / "src"
if str(PKG_SRC) not in sys.path:
    sys.path.insert(0, str(PKG_SRC))

from pragmabot.pipeline import PragmaBot  # noqa: E402
from pragmabot.robot.grasp import TopDownGraspSynthesizer  # noqa: E402
from pragmabot.simple_config import load_config  # noqa: E402


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

    cfg = load_config(REPO_ROOT / "pragmabot" / "config" / "config.yaml")
    cfg.vlm.backend = "stub"
    cfg.embeddings.backend = "stub"
    cfg.robot.backend = "stub"
    cfg.perception.backend = "stub"
    cfg.pipeline.max_steps = 2
    cfg.vlm.detector_mode = "always_complete"
    tmp = Path(tempfile.mkdtemp(prefix="pragmabot_phase4_"))
    cfg.memory.ltm_path = str(tmp / "ltm.csv")
    cfg.memory.embeddings_path = str(tmp / "ltm_embeddings.npy")

    # 1. Grasp synthesizer
    synth = TopDownGraspSynthesizer(cfg)
    cand = synth.synthesize("apple", target_position=np.array([0.4, 0.0, 0.3]))[0]
    print("--- top-down grasp candidate ---")
    print(f"confidence = {cand.confidence}")
    print(f"approach_vector = {cand.approach_vector.tolist()}")
    print("pose_matrix:")
    print(np.round(cand.pose_matrix, 4))

    # 2. Pipeline with stub backends — verify 3D positions flow through.
    bot = PragmaBot(cfg)
    bot.run_task("pick up the apple")
    print("--- stub robot execution log ---")
    print(json.dumps(bot.robot.execution_log, indent=2, default=str))
    pick = next(e for e in bot.robot.execution_log if e["skill"] == "pick")
    assert pick["parameters"]["target_position_3d"] is not None
    print("Pick position from perception:", pick["parameters"]["target_position_3d"])

    # 3. FrankaRobot must raise a friendly RuntimeError on Mac.
    from pragmabot.robot.franka_ros import FrankaRobot, ROS_AVAILABLE

    print(f"ROS_AVAILABLE = {ROS_AVAILABLE}")
    try:
        FrankaRobot(cfg)
    except RuntimeError as exc:
        print(f"FrankaRobot guard fired correctly: {exc}")
    else:
        raise AssertionError("FrankaRobot did not raise on Mac")

    print("Phase 4 Mac smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
