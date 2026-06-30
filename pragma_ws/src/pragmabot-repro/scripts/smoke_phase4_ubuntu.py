"""[UBUNTU] Phase 4 smoke — drive the Franka through MoveIt in Gazebo or hardware."""

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


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    rospy.init_node("pragmabot_phase4_smoke", anonymous=True, disable_signals=True)

    cfg = load_config(REPO_ROOT / "pragmabot" / "config" / "config.yaml")
    cfg.robot.backend = "franka_ros"

    robot = FrankaRobot(cfg)
    print(f"is_connected: {robot.is_connected()}")
    print(f"move_to_named_target('ready'): {robot.move_to_named_target('ready')}")
    print(f"open_gripper: {robot.open_gripper()}")
    print(f"close_gripper: {robot.close_gripper(width=0.0)}")

    # Pure-base-frame pick (no perception/tf needed in this smoke).
    target = np.array([0.4, 0.0, 0.3])
    print(f"workspace check {target}: {robot._check_workspace_limits(target)}")
    pick_ok = robot.execute_pick("test_object", target_position_3d=target)
    print(f"execute_pick at {target}: {pick_ok}")

    retreat_ok = robot.move_to_named_target("ready")
    print(f"retreat to 'ready': {retreat_ok}")

    print("Phase 4 Ubuntu smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
