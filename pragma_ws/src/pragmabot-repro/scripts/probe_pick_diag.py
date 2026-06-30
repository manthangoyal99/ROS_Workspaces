#!/usr/bin/env python3
"""Diagnostic pick — uses FrankaRobot.move_cartesian_path so auto-recovery fires."""
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


def _ee_xyz(robot):
    p = robot._move_group.get_current_pose(robot.ee_link).pose.position
    return (p.x, p.y, p.z)


def step(robot, label, pose):
    before = _ee_xyz(robot)
    ok = robot.move_cartesian_path([pose])
    after = _ee_xyz(robot)
    moved = np.linalg.norm(np.array(after) - np.array(before))
    err = np.linalg.norm(np.array(after) - np.array([pose.position.x, pose.position.y, pose.position.z]))
    print(f"  {label:10s} target=({pose.position.x:.3f},{pose.position.y:.3f},{pose.position.z:.3f}) "
          f"ok={ok} before={tuple(round(c,3) for c in before)} "
          f"after={tuple(round(c,3) for c in after)} moved={moved*1000:.0f}mm err={err*1000:.0f}mm")
    return ok


def main() -> int:
    rospy.init_node("pragmabot_pick_diag", anonymous=True, disable_signals=True)
    cfg = load_config(str(ROOT / "pragmabot" / "config" / "config.yaml"))

    intr = CameraIntrinsics.from_ros_camera_info(
        rospy.wait_for_message(cfg.ros.camera_info_topic, CameraInfo, timeout=5.0)
    )
    rgb   = ros_image_to_numpy(rospy.wait_for_message(cfg.ros.rgb_topic, ImageMsg, timeout=5.0))
    depth = ros_image_to_numpy(rospy.wait_for_message(cfg.ros.depth_topic, ImageMsg, timeout=5.0))

    perception = get_perception(cfg)
    orange = perception.detect(rgb, ["orange"], depth=depth).get_object("orange")
    assert orange is not None
    p_cam = unproject_pixel(*orange.centroid_2d, depth, intr)
    assert p_cam is not None

    buf = tf2_ros.Buffer(); _ = tf2_ros.TransformListener(buf); rospy.sleep(0.5)
    ps = PointStamped()
    ps.header.frame_id = cfg.robot.camera_frame
    ps.header.stamp = rospy.Time(0)
    ps.point.x, ps.point.y, ps.point.z = map(float, p_cam)
    out = buf.transform(ps, cfg.robot.robot_base_frame, rospy.Duration(2.0))
    target = np.array([out.point.x, out.point.y, out.point.z])

    robot = FrankaRobot(cfg)
    print(f"target     : {tuple(round(float(c),3) for c in target)}  ws_ok={robot._check_workspace_limits(target)}")
    print(f"sink depth : {robot.grasp_synthesizer.grasp_height_offset}m  approach: {robot.approach_height_offset}m  retreat: {robot.retreat_height_offset}m")
    print(f"current EE : {tuple(round(c,3) for c in _ee_xyz(robot))}")

    candidates = robot.grasp_synthesizer.synthesize("orange", target_position=target)
    grasp_pose = robot._pose_from_matrix(candidates[0].pose_matrix)
    pre_grasp  = robot._pose_with_xyz(grasp_pose, target + np.array([0, 0, robot.approach_height_offset]))
    retreat    = robot._pose_with_xyz(grasp_pose, target + np.array([0, 0, robot.retreat_height_offset]))

    print()
    print("Press ENTER to run pick sequence, Ctrl+C to abort.")
    with open("/dev/tty") as tty:
        tty.readline()

    robot.open_gripper()
    step(robot, "pre_grasp", pre_grasp)
    step(robot, "grasp",     grasp_pose)
    print(f"  close_gripper -> {robot.close_gripper()}")
    step(robot, "retreat",   retreat)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
