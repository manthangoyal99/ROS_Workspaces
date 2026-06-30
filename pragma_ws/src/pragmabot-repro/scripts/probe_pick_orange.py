#!/usr/bin/env python3
"""[UBUNTU] Supervised single-pick on the live-detected orange."""
import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pragmabot" / "src"))

import numpy as np
import rospy
import tf2_ros
from geometry_msgs.msg import PointStamped
from sensor_msgs.msg import Image as ImageMsg, CameraInfo

from pragmabot.simple_config import load_config
from pragmabot.perception.factory import get_perception
from pragmabot.perception.camera_intrinsics import CameraIntrinsics, unproject_pixel
from pragmabot.ros.image_utils import ros_image_to_numpy
from pragmabot.robot.franka_ros import FrankaRobot


def main() -> int:
    rospy.init_node("pragmabot_pick_probe", anonymous=True, disable_signals=True)
    cfg = load_config(str(ROOT / "pragmabot" / "config" / "config.yaml"))

    intr = CameraIntrinsics.from_ros_camera_info(
        rospy.wait_for_message(cfg.ros.camera_info_topic, CameraInfo, timeout=5.0)
    )
    rgb   = ros_image_to_numpy(rospy.wait_for_message(cfg.ros.rgb_topic, ImageMsg, timeout=5.0))
    depth = ros_image_to_numpy(rospy.wait_for_message(cfg.ros.depth_topic, ImageMsg, timeout=5.0))

    perception = get_perception(cfg)
    result = perception.detect(rgb, ["orange"], depth=depth)
    orange = result.get_object("orange")
    assert orange is not None, "orange not detected"
    p_cam = unproject_pixel(*orange.centroid_2d, depth, intr)
    assert p_cam is not None, "no depth at orange centroid"

    buf = tf2_ros.Buffer(); _ = tf2_ros.TransformListener(buf); rospy.sleep(0.5)
    ps = PointStamped()
    ps.header.frame_id = cfg.robot.camera_frame
    ps.header.stamp = rospy.Time(0)
    ps.point.x, ps.point.y, ps.point.z = map(float, p_cam)
    out = buf.transform(ps, cfg.robot.robot_base_frame, rospy.Duration(2.0))
    target = np.array([out.point.x, out.point.y, out.point.z])

    robot = FrankaRobot(cfg)
    ok = robot._check_workspace_limits(target)
    print(f"orange in base frame : {tuple(round(float(c),3) for c in target)}  workspace_ok={ok}")
    print(f"approach height (z)  : {target[2] + robot.approach_height_offset:.3f}")
    print(f"is_connected         : {robot.is_connected()}")
    print()
    print("============================================================")
    print("REAL ROBOT MOTION: open gripper, pick orange, retreat to safe home.")
    print("Clear the workspace. Press ENTER to continue, Ctrl+C to abort.")
    print("============================================================")
    input()

    print(f"open_gripper     : {robot.open_gripper()}")
    print(f"execute_pick     : {robot.execute_pick('orange', target_position_3d=target)}")
    print(f"move_to_safe_home: {robot.move_to_safe_home()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
