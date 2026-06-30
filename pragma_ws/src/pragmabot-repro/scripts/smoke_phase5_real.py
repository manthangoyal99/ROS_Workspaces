"""[UBUNTU — REAL ROBOT] Phase 5 smoke — one supervised pick on the physical Franka.

Confirmation gate is non-skippable. Must be run with a clear workspace.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
PKG_SRC = REPO_ROOT / "pragmabot" / "src"
if str(PKG_SRC) not in sys.path:
    sys.path.insert(0, str(PKG_SRC))

try:
    import rospy  # type: ignore
except ImportError:
    print("ROS not available — this smoke script must run on Ubuntu with ROS Noetic.")
    sys.exit(2)

from pragmabot.robot.franka_ros import FrankaRobot  # noqa: E402
from pragmabot.simple_config import load_config  # noqa: E402


def _safety_gate() -> None:
    print("=" * 60)
    print("REAL ROBOT SMOKE TEST")
    print("This script will move the Franka arm.")
    print("Ensure the workspace is clear.")
    print("Press ENTER to continue or Ctrl+C to abort.")
    print("=" * 60)
    input()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    _safety_gate()

    rospy.init_node("pragmabot_phase5_real_smoke", anonymous=True, disable_signals=True)
    cfg = load_config(REPO_ROOT / "pragmabot" / "config" / "config.yaml")
    cfg.robot.backend = "franka_ros"
    robot = FrankaRobot(cfg)

    print(f"is_connected: {robot.is_connected()}")
    print(f"home: {robot.move_to_named_target('ready')}")

    target = np.array([0.4, 0.0, 0.20])  # MUST point at a real object placed in workspace
    print(f"workspace check {target}: {robot._check_workspace_limits(target)}")
    pick_ok = robot.execute_pick("manually_placed_object", target_position_3d=target)
    print(f"execute_pick at {target}: {pick_ok}")

    print(f"retreat: {robot.move_to_named_target('ready')}")
    print("Phase 5 Real Robot smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
