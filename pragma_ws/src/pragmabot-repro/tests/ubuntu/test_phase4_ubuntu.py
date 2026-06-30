"""Phase 4 Ubuntu tests — require ROS Noetic + MoveIt + a running move_group.

These exercise FrankaRobot against a live panda_moveit setup (typically
franka_gazebo). Skip cleanly when ROS or MoveIt isn't installed.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

try:
    import rospy  # type: ignore  # noqa: F401
    import moveit_commander  # type: ignore  # noqa: F401

    ROS_AVAILABLE = True
except ImportError:
    ROS_AVAILABLE = False

pytestmark = pytest.mark.skipif(not ROS_AVAILABLE, reason="ROS/MoveIt not available")


from pragmabot.robot.franka_ros import FrankaRobot  # noqa: E402
from pragmabot.simple_config import load_config  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "pragmabot" / "config" / "config.yaml"


@pytest.fixture(scope="module")
def cfg():
    config = load_config(CONFIG_PATH)
    config.robot.backend = "franka_ros"
    return config


@pytest.fixture(scope="module")
def robot(cfg):
    # ROS node init is handled once per session by tests/ubuntu/conftest.py.
    return FrankaRobot(cfg)


def test_franka_robot_instantiates(robot):
    assert robot is not None
    assert robot.backend_name == "franka_ros"


def test_moveit_connection(robot):
    assert robot.is_connected() is True


def test_open_close_gripper(robot):
    assert robot.open_gripper() is True
    assert robot.close_gripper(width=0.0, force=5.0) in (True, False)
    # We don't assert closure success — depends on whether an object is in
    # the gripper. open() must always succeed.


def test_ik_feasibility_reachable(robot, cfg):
    from geometry_msgs.msg import Pose  # type: ignore

    pose = Pose()
    pose.position.x = 0.4
    pose.position.y = 0.0
    pose.position.z = 0.4
    # EE pointing straight down (quaternion for 180° about X).
    pose.orientation.x = 1.0
    pose.orientation.y = 0.0
    pose.orientation.z = 0.0
    pose.orientation.w = 0.0
    assert robot._check_ik_feasibility(pose) is True


def test_ik_feasibility_unreachable(robot):
    from geometry_msgs.msg import Pose  # type: ignore

    pose = Pose()
    pose.position.x = 10.0
    pose.position.y = 10.0
    pose.position.z = 10.0
    pose.orientation.w = 1.0
    assert robot._check_ik_feasibility(pose) is False


def test_transform_point_to_base_identity(robot):
    """When source==base, the point is returned unchanged."""
    p = np.array([0.4, 0.0, 0.3])
    out = robot.transform_point_to_base(p, source_frame=robot.base_frame)
    assert np.allclose(out, p)


def test_move_to_named_target_ready(robot):
    assert robot.move_to_named_target("ready") is True


def test_cartesian_path_short(robot):
    """Two waypoints, a few cm apart, should plan and execute."""
    from geometry_msgs.msg import Pose  # type: ignore

    state = robot._move_group.get_current_pose(robot.ee_link).pose
    wp1 = Pose()
    wp1.position.x = state.position.x
    wp1.position.y = state.position.y
    wp1.position.z = state.position.z + 0.03
    wp1.orientation = state.orientation
    wp2 = Pose()
    wp2.position.x = state.position.x
    wp2.position.y = state.position.y
    wp2.position.z = state.position.z - 0.03
    wp2.orientation = state.orientation
    assert robot.move_cartesian_path([wp1, wp2]) is True


def test_workspace_limits_reject_out_of_bounds(robot):
    """Out-of-bounds positions must be rejected without raising."""
    assert robot._check_workspace_limits(np.array([5.0, 0.0, 0.3])) is False
    assert robot._check_workspace_limits(np.array([0.4, 0.0, 0.3])) is True
