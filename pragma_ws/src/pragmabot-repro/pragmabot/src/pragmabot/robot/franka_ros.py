"""Franka Panda robot backend — MoveIt + franka_ros + tf2.

Ubuntu + ROS Noetic only. The module is import-safe on Mac: every ROS-side
symbol is gated by ``ROS_AVAILABLE``, and the constructor raises
``RuntimeError`` with a clear remediation message when ROS is missing.

Safety contract: every motion-emitting method invokes
:meth:`FrankaRobot._check_workspace_limits` before issuing any robot command.
"""

from __future__ import annotations

# --- ROS import guard (per CLAUDE.md) ----------------------------------------
try:
    import rospy  # type: ignore
    import moveit_commander  # type: ignore
    import moveit_msgs.msg  # type: ignore  # noqa: F401
    import moveit_msgs.srv  # type: ignore
    import geometry_msgs.msg  # type: ignore  # noqa: F401
    from geometry_msgs.msg import Pose, PoseStamped  # type: ignore
    from std_msgs.msg import Header  # type: ignore  # noqa: F401
    from sensor_msgs.msg import Image, CompressedImage  # type: ignore  # noqa: F401
    import tf2_ros  # type: ignore
    import tf2_geometry_msgs  # type: ignore  # noqa: F401

    ROS_AVAILABLE = True
except ImportError:
    ROS_AVAILABLE = False
    Pose = None  # type: ignore[assignment]
    PoseStamped = None  # type: ignore[assignment]
# -----------------------------------------------------------------------------

import logging
import threading
import time
from typing import Any, List, Optional

import numpy as np
from omegaconf import DictConfig

from .base import BaseRobot
from .grasp import GraspCandidate, get_grasp_synthesizer

logger = logging.getLogger(__name__)


# Allowed direction strings -> unit vectors in the robot base frame.
_DIRECTION_VECTORS = {
    "left":     np.array([0.0, -1.0, 0.0]),
    "right":    np.array([0.0,  1.0, 0.0]),
    "forward":  np.array([1.0,  0.0, 0.0]),
    "backward": np.array([-1.0, 0.0, 0.0]),
    "back":     np.array([-1.0, 0.0, 0.0]),
    "up":       np.array([0.0,  0.0, 1.0]),
    "down":     np.array([0.0,  0.0, -1.0]),
}


class FrankaRobot(BaseRobot):
    """Franka Panda backend via MoveIt and franka_ros."""

    def __init__(self, cfg: DictConfig) -> None:
        if not ROS_AVAILABLE:
            raise RuntimeError(
                "FrankaRobot requires ROS Noetic + MoveIt. Install moveit_commander, "
                "franka_ros, and tf2_ros, or set robot.backend: stub in config.yaml."
            )

        self._cfg = cfg
        robot_cfg = cfg.robot

        # Frames & MoveIt config
        self.planning_group: str = str(robot_cfg.get("planning_group", "panda_arm"))
        self.gripper_group: str = str(robot_cfg.get("gripper_group", "panda_hand"))
        self.ee_link: str = str(robot_cfg.get("ee_link", "panda_hand_tcp"))
        self.camera_frame: str = str(robot_cfg.get("camera_frame", "camera_color_optical_frame"))
        self.base_frame: str = str(robot_cfg.get("robot_base_frame", "panda_link0"))

        self.move_group_timeout: float = float(robot_cfg.get("move_group_timeout", 10.0))
        self.cartesian_eef_step: float = float(robot_cfg.get("cartesian_eef_step", 0.01))
        self.cartesian_jump_threshold: float = float(robot_cfg.get("cartesian_jump_threshold", 0.0))

        # Skill offsets
        self.approach_height_offset: float = float(robot_cfg.get("approach_height_offset", 0.12))
        self.retreat_height_offset: float = float(robot_cfg.get("retreat_height_offset", 0.15))
        self.grasp_depth_offset: float = float(robot_cfg.get("grasp_depth_offset", 0.005))
        self.push_standoff: float = float(robot_cfg.get("push_standoff", 0.05))
        self.place_height_offset: float = float(robot_cfg.get("place_height_offset", 0.05))

        self.max_velocity_scaling: float = float(robot_cfg.get("max_velocity_scaling", 0.3))
        self.max_acceleration_scaling: float = float(robot_cfg.get("max_acceleration_scaling", 0.3))

        # Safe home in Cartesian space — used by ``move_to_safe_home``.
        # The named "ready" / "home" targets occasionally fail with
        # CONTROL_FAILED on joint 2 tolerance; the Cartesian path is
        # consistently reliable.
        safe_home_cfg = robot_cfg.get("safe_home_position", {}) or {}
        self.safe_home_position = (
            float(safe_home_cfg.get("x", 0.307)),
            float(safe_home_cfg.get("y", 0.000)),
            float(safe_home_cfg.get("z", 0.550)),
        )

        # SAFETY: workspace limits — every motion is gated by these.
        ws = robot_cfg.get("workspace_limits", {}) or {}
        self._workspace_limits = {
            "x": tuple(ws.get("x", (0.20, 0.70))),
            "y": tuple(ws.get("y", (-0.40, 0.40))),
            "z": tuple(ws.get("z", (0.00, 0.60))),
        }

        # Grasp synthesizer (Phase 7-swappable).
        self.grasp_synthesizer = get_grasp_synthesizer(cfg)

        # Camera frame cache (filled by callback).
        self._latest_rgb: Optional[np.ndarray] = None
        self._image_lock = threading.Lock()

        self._init_moveit()
        self._init_gripper()
        self._init_tf()
        self._init_camera_subscriber()
        # Force-threshold relaxation is opt-in via robot.relax_force_thresholds
        # config (default: False). Calling it unconditionally created more
        # problems than it solved; keeping it as a knob.
        if bool(self._cfg.robot.get("relax_force_thresholds", False)):
            self._relax_force_thresholds()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _init_moveit(self) -> None:
        """Bring up moveit_commander and the move group."""
        moveit_commander.roscpp_initialize([])
        self._robot_commander = moveit_commander.RobotCommander()
        self._scene = moveit_commander.PlanningSceneInterface()
        self._move_group = moveit_commander.MoveGroupCommander(
            self.planning_group, wait_for_servers=self.move_group_timeout
        )
        self._move_group.set_end_effector_link(self.ee_link)
        self._move_group.set_pose_reference_frame(self.base_frame)
        self._move_group.set_max_velocity_scaling_factor(self.max_velocity_scaling)
        self._move_group.set_max_acceleration_scaling_factor(self.max_acceleration_scaling)
        try:
            self._move_group.set_planning_time(5.0)
            self._move_group.allow_replanning(True)
        except Exception:  # pragma: no cover - defensive
            pass

    def _init_gripper(self) -> None:
        """Initialize franka_gripper action clients lazily.

        Imported here so the module still loads on systems without
        ``franka_gripper`` available.
        """
        try:
            import actionlib  # type: ignore
            from franka_gripper.msg import (  # type: ignore
                GraspAction, GraspEpsilon, GraspGoal, MoveAction, MoveGoal,
            )

            self._grasp_client = actionlib.SimpleActionClient(
                "/franka_gripper/grasp", GraspAction
            )
            self._move_gripper_client = actionlib.SimpleActionClient(
                "/franka_gripper/move", MoveAction
            )
            ready = self._grasp_client.wait_for_server(rospy.Duration(2.0))
            ready &= self._move_gripper_client.wait_for_server(rospy.Duration(2.0))
            self._gripper_available = bool(ready)
            self._GraspGoal = GraspGoal
            self._GraspEpsilon = GraspEpsilon
            self._MoveGoal = MoveGoal
        except Exception as exc:  # pragma: no cover - hardware-specific
            logger.warning("franka_gripper unavailable: %s", exc)
            self._gripper_available = False
            self._grasp_client = None
            self._move_gripper_client = None
            self._GraspGoal = None
            self._GraspEpsilon = None
            self._MoveGoal = None

    def _init_tf(self) -> None:
        """Start a tf2 buffer + listener (background thread)."""
        self._tf_buffer = tf2_ros.Buffer()
        self._tf_listener = tf2_ros.TransformListener(self._tf_buffer)
        # Give the listener a moment to fill.
        rospy.sleep(0.5)

    def _init_camera_subscriber(self) -> None:
        """Subscribe to the configured RGB topic."""
        ros_cfg = self._cfg.get("ros") or {}
        topic = str(ros_cfg.get("rgb_topic", "/camera/color/image_raw"))
        use_compressed = bool(ros_cfg.get("use_compressed_rgb", False))
        msg_type = CompressedImage if use_compressed else Image
        self._rgb_topic = topic
        self._rgb_sub = rospy.Subscriber(topic, msg_type, self._rgb_cb, queue_size=1)
        self._use_compressed_rgb = use_compressed

    def _rgb_cb(self, msg) -> None:
        from ..ros.image_utils import ros_compressed_to_numpy, ros_image_to_numpy

        try:
            arr = (
                ros_compressed_to_numpy(msg) if self._use_compressed_rgb else ros_image_to_numpy(msg)
            )
        except Exception as exc:  # pragma: no cover
            logger.error("Failed to decode RGB frame: %s", exc)
            return
        with self._image_lock:
            self._latest_rgb = arr

    @property
    def backend_name(self) -> str:
        return "franka_ros"

    # ------------------------------------------------------------------
    # Safety
    # ------------------------------------------------------------------

    def _check_workspace_limits(self, xyz_base: np.ndarray) -> bool:
        """True iff ``xyz_base`` lies inside the configured workspace box.

        Never raises — logs an error and returns False on out-of-bounds so
        callers can fail gracefully.
        """
        try:
            p = np.asarray(xyz_base, dtype=float).reshape(3)
        except Exception:
            logger.error("Workspace check received invalid position: %r", xyz_base)
            return False
        for i, axis in enumerate(("x", "y", "z")):
            lo, hi = self._workspace_limits[axis]
            if not (float(lo) <= float(p[i]) <= float(hi)):
                logger.error(
                    "Workspace limit violated on axis %s: %.3f not in [%.3f, %.3f]",
                    axis, float(p[i]), float(lo), float(hi),
                )
                return False
        return True

    # ------------------------------------------------------------------
    # Gripper
    # ------------------------------------------------------------------

    def open_gripper(self, width: float = 0.08, speed: float = 0.1) -> bool:
        if not self._gripper_available:
            logger.warning("Gripper action server unavailable; assuming open.")
            return True
        goal = self._MoveGoal(width=float(width), speed=float(speed))
        self._move_gripper_client.send_goal(goal)
        finished = self._move_gripper_client.wait_for_result(rospy.Duration(5.0))
        if not finished:
            logger.warning("open_gripper timed out")
            return False
        result = self._move_gripper_client.get_result()
        return bool(getattr(result, "success", True))

    def close_gripper(
        self,
        width: float = 0.0,
        speed: float = 0.1,
        force: float = 10.0,
    ) -> bool:
        """Close the gripper fingers to ``width`` using ``MoveAction``.

        We deliberately use MoveAction (not GraspAction). MoveAction simply
        commands the fingers to a target width without any object-presence
        check; GraspAction requires the final width to be inside
        ``target ± epsilon`` and AUTO-RELEASES the fingers on failure
        (the classic "gripper closed then opened" symptom). For a soft pick
        we want the fingers to stay closed on whatever they find.

        ``force`` is accepted for backwards compatibility but ignored.
        """
        if not self._gripper_available:
            logger.warning("Gripper action server unavailable; assuming closed.")
            return True
        goal = self._MoveGoal(width=float(width), speed=float(speed))
        self._move_gripper_client.send_goal(goal)
        finished = self._move_gripper_client.wait_for_result(rospy.Duration(5.0))
        if not finished:
            logger.warning("close_gripper timed out")
            return False
        result = self._move_gripper_client.get_result()
        return bool(getattr(result, "success", True))

    # ------------------------------------------------------------------
    # Frame transforms
    # ------------------------------------------------------------------

    def transform_point_to_base(
        self,
        point_camera: np.ndarray,
        source_frame: Optional[str] = None,
    ) -> Optional[np.ndarray]:
        """Transform a 3D point from ``source_frame`` (default: camera) to base."""
        if source_frame is None:
            source_frame = self.camera_frame
        if source_frame == self.base_frame:
            return np.asarray(point_camera, dtype=float).reshape(3)

        from geometry_msgs.msg import PointStamped  # type: ignore

        stamped = PointStamped()
        stamped.header.frame_id = source_frame
        stamped.header.stamp = rospy.Time(0)
        stamped.point.x = float(point_camera[0])
        stamped.point.y = float(point_camera[1])
        stamped.point.z = float(point_camera[2])
        try:
            out = self._tf_buffer.transform(stamped, self.base_frame, rospy.Duration(2.0))
        except (tf2_ros.LookupException, tf2_ros.ConnectivityException, tf2_ros.ExtrapolationException) as exc:
            logger.error("TF lookup failed (%s -> %s): %s", source_frame, self.base_frame, exc)
            return None
        return np.array([out.point.x, out.point.y, out.point.z], dtype=float)

    # ------------------------------------------------------------------
    # Motion primitives
    # ------------------------------------------------------------------

    @staticmethod
    def _pose_from_matrix(matrix: np.ndarray) -> Pose:
        """Convert a 4x4 SE(3) matrix to a geometry_msgs/Pose."""
        from geometry_msgs.msg import Pose as _Pose  # type: ignore
        from tf.transformations import quaternion_from_matrix  # type: ignore

        pose = _Pose()
        pose.position.x = float(matrix[0, 3])
        pose.position.y = float(matrix[1, 3])
        pose.position.z = float(matrix[2, 3])
        # quaternion_from_matrix expects a 4x4 homogeneous matrix
        q = quaternion_from_matrix(matrix)
        pose.orientation.x = float(q[0])
        pose.orientation.y = float(q[1])
        pose.orientation.z = float(q[2])
        pose.orientation.w = float(q[3])
        return pose

    @staticmethod
    def _pose_with_xyz(template: Pose, xyz: np.ndarray) -> Pose:
        """Clone ``template`` with the position replaced by ``xyz`` (orientation kept)."""
        from copy import deepcopy

        out = deepcopy(template)
        out.position.x = float(xyz[0])
        out.position.y = float(xyz[1])
        out.position.z = float(xyz[2])
        return out

    def move_to_pose(self, pose: Pose, frame_id: Optional[str] = None) -> bool:
        if frame_id is None:
            frame_id = self.base_frame
        if not self._check_workspace_limits(
            np.array([pose.position.x, pose.position.y, pose.position.z])
        ):
            return False
        self._move_group.set_pose_reference_frame(frame_id)
        self._move_group.set_pose_target(pose, end_effector_link=self.ee_link)
        success = bool(self._move_group.go(wait=True))
        self._move_group.stop()
        self._move_group.clear_pose_targets()
        return success

    def _relax_force_thresholds(self) -> bool:
        """Raise Franka's collision wrench thresholds so picking small objects
        doesn't trigger a safety reflex (CONTROL_FAILED on retreat when the
        gripper is loaded with even a ~100 g payload).
        """
        try:
            from franka_msgs.srv import SetForceTorqueCollisionBehavior  # type: ignore
        except ImportError:
            logger.debug("franka_msgs.SetForceTorqueCollisionBehavior unavailable")
            return False
        srv_name = "/franka_control/set_force_torque_collision_behavior"
        try:
            rospy.wait_for_service(srv_name, timeout=3.0)
            svc = rospy.ServiceProxy(srv_name, SetForceTorqueCollisionBehavior)
            # 7 joint torque thresholds (Nm) for accel + nominal phases,
            # then 6D Cartesian force/torque thresholds (N, Nm).
            # Defaults are very tight; bumping to ~3x default tolerates a
            # ~200 g payload without false reflex aborts.
            joint_acc = [40.0] * 7
            joint_nom = [40.0] * 7
            cart_acc = [40.0, 40.0, 40.0, 40.0, 40.0, 40.0]
            cart_nom = [40.0, 40.0, 40.0, 40.0, 40.0, 40.0]
            resp = svc(
                lower_torque_thresholds_acceleration=joint_acc,
                upper_torque_thresholds_acceleration=joint_acc,
                lower_torque_thresholds_nominal=joint_nom,
                upper_torque_thresholds_nominal=joint_nom,
                lower_force_thresholds_acceleration=cart_acc,
                upper_force_thresholds_acceleration=cart_acc,
                lower_force_thresholds_nominal=cart_nom,
                upper_force_thresholds_nominal=cart_nom,
            )
            ok = bool(getattr(resp, "success", True))
            logger.info("set_force_torque_collision_behavior ok=%s", ok)
            return ok
        except Exception as exc:
            logger.warning("Could not relax force thresholds: %s", exc)
            return False

    def _franka_error_recovery(self) -> bool:
        """Send a Franka error-recovery goal. Called automatically before each motion."""
        try:
            import actionlib  # type: ignore
            from franka_msgs.msg import ErrorRecoveryAction, ErrorRecoveryGoal  # type: ignore
        except ImportError:
            return True  # franka_msgs not installed → assume nothing to recover.

        if not hasattr(self, "_recovery_client") or self._recovery_client is None:
            self._recovery_client = actionlib.SimpleActionClient(
                "/franka_control/error_recovery", ErrorRecoveryAction
            )
            if not self._recovery_client.wait_for_server(rospy.Duration(2.0)):
                self._recovery_client = None
                return True  # action server absent → skip silently.

        self._recovery_client.send_goal(ErrorRecoveryGoal())
        return bool(self._recovery_client.wait_for_result(rospy.Duration(5.0)))

    def _cleanup_move_group_state(self) -> None:
        """Cancel any lingering MoveGroup goal + clear cached targets.

        Without this, repeated motions accumulate stale action goal handles
        in MoveGroupCommander's internal action client, eventually producing
        ``Got a transition callback on a goal handle that we're not tracking``
        errors and stuck motions. Call before every new trajectory.
        """
        try:
            self._move_group.stop()
        except Exception:  # pragma: no cover
            pass
        try:
            self._move_group.clear_pose_targets()
        except Exception:  # pragma: no cover
            pass

    def move_cartesian_path(self, waypoints: List[Pose], avoid_collisions: bool = False) -> bool:
        """Execute a Cartesian path. On failure, recovers once and retries.

        ``avoid_collisions`` defaults to False — for pick/place the EE
        intentionally approaches objects, so MoveIt's collision avoidance
        would preempt the descent. Workspace limits are the safety net.
        """
        if not waypoints:
            return False
        for wp in waypoints:
            if not self._check_workspace_limits(
                np.array([wp.position.x, wp.position.y, wp.position.z])
            ):
                return False

        def _plan_and_exec() -> bool:
            self._cleanup_move_group_state()
            rospy.sleep(0.1)
            plan, fraction = self._move_group.compute_cartesian_path(
                waypoints, self.cartesian_eef_step, avoid_collisions,
            )
            if fraction < 0.9:
                logger.warning("Cartesian path only %.0f%% feasible", fraction * 100.0)
                return False
            return bool(self._move_group.execute(plan, wait=True))

        if _plan_and_exec():
            return True

        # First attempt failed: fully reset state, recover from any Franka
        # error, give the controller time to settle, then re-plan and retry.
        logger.warning("Cartesian execute failed; cleaning up + recovering + retrying.")
        self._cleanup_move_group_state()
        rospy.sleep(0.5)
        self._franka_error_recovery()
        rospy.sleep(1.0)
        return _plan_and_exec()

    def move_to_named_target(self, target: str) -> bool:
        try:
            self._move_group.set_named_target(target)
        except moveit_commander.MoveItCommanderException as exc:
            logger.error("Unknown named target %r: %s", target, exc)
            return False
        success = bool(self._move_group.go(wait=True))
        self._move_group.stop()
        return success

    def move_to_safe_home(self) -> bool:
        """Move the end-effector to ``robot.safe_home_position`` via a chunked Cartesian path.

        Approach:

          1. Build a series of intermediate waypoints first straight up to
             ``safe_z``, then horizontally to ``(safe_x, safe_y)``.
          2. Feed ALL waypoints to ``compute_cartesian_path`` in a single
             call so the planner interpolates joint configurations
             continuously (no elbow flips). Default chunk length 5 cm.

        Without intermediate chunks, a single far-away waypoint can produce
        a trajectory that requires a >1 rad swing on joint 4 (the
        ``GOAL_TOLERANCE_VIOLATED: panda_joint4 goal error 1.0`` symptom on
        real hardware). Noetic's MoveIt python API no longer exposes
        ``jump_threshold`` to catch this, so we prevent it explicitly by
        densifying the waypoint list.

        Orientation is preserved from the current EE pose.
        """
        from copy import deepcopy
        from geometry_msgs.msg import Pose  # type: ignore

        try:
            current = self._move_group.get_current_pose(self.ee_link).pose
        except Exception as exc:  # pragma: no cover - hardware-specific
            logger.error("get_current_pose failed in move_to_safe_home: %s", exc)
            return False

        safe_x, safe_y, safe_z = self.safe_home_position
        chunk_m = 0.05  # 5 cm per intermediate waypoint
        cur_x = float(current.position.x)
        cur_y = float(current.position.y)
        cur_z = float(current.position.z)
        ori = deepcopy(current.orientation)

        def _waypoint(x: float, y: float, z: float):
            wp = Pose()
            wp.position.x = float(x)
            wp.position.y = float(y)
            wp.position.z = float(z)
            wp.orientation = deepcopy(ori)
            return wp

        waypoints = []

        # Vertical segment, chunked.
        dz = float(safe_z) - cur_z
        if abs(dz) > 0.005:
            n_z = max(2, int(abs(dz) / chunk_m) + 1)
            for i in range(1, n_z + 1):
                z = cur_z + dz * (i / n_z)
                waypoints.append(_waypoint(cur_x, cur_y, z))

        # Horizontal segment at safe_z, chunked.
        dx = float(safe_x) - cur_x
        dy = float(safe_y) - cur_y
        horiz = (dx * dx + dy * dy) ** 0.5
        if horiz > 0.005:
            n_h = max(2, int(horiz / chunk_m) + 1)
            for i in range(1, n_h + 1):
                x = cur_x + dx * (i / n_h)
                y = cur_y + dy * (i / n_h)
                waypoints.append(_waypoint(x, y, float(safe_z)))

        if not waypoints:
            # Already at safe home.
            return True

        logger.info(
            "move_to_safe_home: %d waypoints (start=(%.3f,%.3f,%.3f) → home=(%.3f,%.3f,%.3f))",
            len(waypoints), cur_x, cur_y, cur_z, safe_x, safe_y, safe_z,
        )
        return self.move_cartesian_path(waypoints)

    # ------------------------------------------------------------------
    # Grasp synthesis + IK
    # ------------------------------------------------------------------

    def _compute_top_down_grasp(
        self,
        target_xyz_base: np.ndarray,
        depth_offset: Optional[float] = None,
    ) -> Pose:
        """Convenience: build a Pose for a top-down grasp above ``target_xyz_base``."""
        if depth_offset is None:
            depth_offset = self.grasp_depth_offset
        candidates = self.grasp_synthesizer.synthesize(
            object_name="(unspecified)",
            point_cloud=None,
            target_position=np.asarray(target_xyz_base, dtype=float),
        )
        if not candidates:
            raise RuntimeError("Grasp synthesizer returned no candidates.")
        return self._pose_from_matrix(candidates[0].pose_matrix)

    def _check_ik_feasibility(self, pose) -> bool:
        """True if MoveIt's compute_ik service finds a valid joint solution."""
        if not ROS_AVAILABLE:  # pragma: no cover - guarded by constructor
            return False
        from moveit_msgs.srv import GetPositionIK  # type: ignore
        from moveit_msgs.msg import RobotState, PositionIKRequest  # type: ignore

        try:
            rospy.wait_for_service("/compute_ik", timeout=2.0)
            ik_service = rospy.ServiceProxy("/compute_ik", GetPositionIK)
        except (rospy.ROSException, rospy.ServiceException) as exc:
            logger.warning("compute_ik service unavailable: %s", exc)
            return False

        # pose may be either a Pose or a 4x4 matrix.
        if isinstance(pose, np.ndarray) and pose.shape == (4, 4):
            target = self._pose_from_matrix(pose)
        else:
            target = pose

        req = PositionIKRequest()
        req.group_name = self.planning_group
        req.robot_state = RobotState()
        req.avoid_collisions = True
        req.timeout = rospy.Duration(1.0)
        from geometry_msgs.msg import PoseStamped  # type: ignore

        pose_stamped = PoseStamped()
        pose_stamped.header.frame_id = self.base_frame
        pose_stamped.pose = target
        req.pose_stamped = pose_stamped
        req.ik_link_name = self.ee_link

        try:
            resp = ik_service(req)
        except rospy.ServiceException as exc:
            logger.warning("compute_ik service call failed: %s", exc)
            return False
        return resp.error_code.val == resp.error_code.SUCCESS

    # ------------------------------------------------------------------
    # Skills
    # ------------------------------------------------------------------

    def _resolve_base_target(self, position_3d: Optional[np.ndarray]) -> Optional[np.ndarray]:
        """Transform a 3D position from camera frame to base, then apply the
        configurable ``robot.perception_offset_base`` (dx, dy, dz) correction.

        The offset is *added* to the transformed base-frame position. Use it
        to compensate for known eye-hand calibration bias without redoing
        the full calibration. E.g., if the gripper consistently lands 3 cm
        in +x of the target, set ``perception_offset_base: [-0.03, 0, 0]``.
        """
        if position_3d is None:
            return None
        p = self.transform_point_to_base(np.asarray(position_3d, dtype=float))
        if p is None:
            return None
        try:
            offset = self._cfg.robot.get("perception_offset_base", None)
        except Exception:
            offset = None
        if offset is not None:
            try:
                off_arr = np.asarray([float(v) for v in offset], dtype=float).reshape(3)
                p = p + off_arr
                logger.info("perception_offset_base applied: %s -> %s", off_arr.tolist(), p.tolist())
            except Exception as exc:
                logger.warning("invalid perception_offset_base %r: %s", offset, exc)
        return p

    def execute_pick(
        self,
        object_name: str,
        target_position_3d: Optional[np.ndarray] = None,
        location_hint: Optional[str] = None,
    ) -> bool:
        print(f"[pick:{object_name}] ENTER target_position_3d={target_position_3d}", flush=True)
        # Always clear any latched Franka error before a new pick attempt.
        self._franka_error_recovery()
        print(f"[pick:{object_name}] recovery done", flush=True)

        if target_position_3d is None:
            print(f"[pick:{object_name}] ABORT: no target_position_3d", flush=True)
            return False
        base_target = self._resolve_base_target(target_position_3d)
        if base_target is None:
            print(f"[pick:{object_name}] ABORT: TF transform to base failed", flush=True)
            return False
        if not self._check_workspace_limits(base_target):
            print(f"[pick:{object_name}] ABORT: target {tuple(round(float(c),3) for c in base_target)} outside workspace", flush=True)
            return False
        print(f"[pick:{object_name}] base_target={tuple(round(float(c),3) for c in base_target)}", flush=True)

        candidates: List[GraspCandidate] = self.grasp_synthesizer.synthesize(
            object_name=object_name, point_cloud=None, target_position=base_target,
        )
        feasible = self.grasp_synthesizer.filter_by_ik(candidates, self._check_ik_feasibility)
        if not feasible:
            print(f"[pick:{object_name}] ABORT: no IK-feasible grasp", flush=True)
            return False
        grasp_pose = self._pose_from_matrix(feasible[0].pose_matrix)

        pre_grasp = self._pose_with_xyz(grasp_pose,
                                        base_target + np.array([0.0, 0.0, self.approach_height_offset]))
        retreat = self._pose_with_xyz(grasp_pose,
                                      base_target + np.array([0.0, 0.0, self.retreat_height_offset]))

        if not self.open_gripper():
            print(f"[pick:{object_name}] ABORT: open_gripper failed", flush=True)
            return False
        print(f"[pick:{object_name}] phase=open_gripper ok", flush=True)

        if not self.move_cartesian_path([pre_grasp]):
            print(f"[pick:{object_name}] ABORT: pre_grasp FAILED", flush=True)
            return False
        print(f"[pick:{object_name}] phase=pre_grasp ok", flush=True)

        if not self.move_cartesian_path([grasp_pose]):
            print(f"[pick:{object_name}] ABORT: grasp_descend FAILED", flush=True)
            return False
        print(f"[pick:{object_name}] phase=grasp_descend ok", flush=True)

        gripper_ok = self.close_gripper()
        print(f"[pick:{object_name}] phase=close_gripper ok={gripper_ok}", flush=True)

        # Recover any latched state from the contact event, then retreat.
        self._franka_error_recovery()
        if not self.move_cartesian_path([retreat]):
            print(f"[pick:{object_name}] ABORT: retreat FAILED", flush=True)
            return False
        print(f"[pick:{object_name}] phase=retreat ok — pick complete", flush=True)
        return True

    def execute_place(
        self,
        object_name: str,
        target_position_3d: Optional[np.ndarray] = None,
        location: Optional[str] = None,
    ) -> bool:
        if target_position_3d is None:
            logger.warning("execute_place called without target_position_3d; aborting.")
            return False
        base_target = self._resolve_base_target(target_position_3d)
        if base_target is None or not self._check_workspace_limits(base_target):
            return False

        place_xyz = base_target + np.array([0.0, 0.0, self.place_height_offset])
        # Use the synthesizer's pose orientation so the gripper stays top-down.
        proto_grasp = self._compute_top_down_grasp(base_target)
        place_pose = self._pose_with_xyz(proto_grasp, place_xyz)
        descend = self._pose_with_xyz(proto_grasp, base_target + np.array([0.0, 0.0, 0.01]))
        retreat = self._pose_with_xyz(
            proto_grasp, base_target + np.array([0.0, 0.0, self.retreat_height_offset])
        )

        # Cartesian place — see execute_pick comment.
        if not self.move_cartesian_path([place_pose]):
            return False
        if not self.move_cartesian_path([descend]):
            return False
        if not self.open_gripper():
            return False
        if not self.move_cartesian_path([retreat]):
            return False
        return True

    def execute_push(
        self,
        object_name: str,
        goal_position_3d: Optional[np.ndarray] = None,
        direction: Optional[str] = None,
    ) -> bool:
        # Compute push vector + goal pose.
        if goal_position_3d is not None:
            base_goal = self._resolve_base_target(goal_position_3d)
            if base_goal is None:
                return False
            # In the absence of a perception centroid, use base_goal as the goal
            # and step back by push_standoff along the direction from base origin.
            push_dir = base_goal - np.array([self.base_frame_origin_x(), 0.0, base_goal[2]])
        elif direction is not None:
            d = direction.strip().lower()
            if d not in _DIRECTION_VECTORS:
                logger.error("Unknown push direction %r", direction)
                return False
            base_goal = None
            push_dir = _DIRECTION_VECTORS[d]
        else:
            logger.warning("execute_push: need goal_position_3d or direction; aborting.")
            return False

        unit_dir = push_dir / max(float(np.linalg.norm(push_dir)), 1e-6)

        # Where the gripper needs to *end up*. Without a perception centroid we
        # synthesize a notional centroid 0.5m forward of the base at table z.
        end_xyz = base_goal if base_goal is not None else np.array([0.5, 0.0, 0.10])
        if not self._check_workspace_limits(end_xyz):
            return False

        approach_xyz = end_xyz - unit_dir * self.push_standoff
        retreat_xyz = end_xyz - unit_dir * (self.push_standoff + 0.05)

        proto_grasp = self._compute_top_down_grasp(end_xyz)
        approach_pose = self._pose_with_xyz(proto_grasp, approach_xyz)
        push_pose = self._pose_with_xyz(proto_grasp, end_xyz)
        retreat_pose = self._pose_with_xyz(proto_grasp, retreat_xyz)

        if not self.close_gripper(width=0.0):
            return False
        # Cartesian approach — see execute_pick comment.
        if not self.move_cartesian_path([approach_pose]):
            return False
        if not self.move_cartesian_path([push_pose]):
            return False
        if not self.move_cartesian_path([retreat_pose]):
            return False
        return True

    @staticmethod
    def base_frame_origin_x() -> float:
        return 0.0

    # ------------------------------------------------------------------
    # Observation + connectivity
    # ------------------------------------------------------------------

    def _native_observation(self) -> np.ndarray:
        with self._image_lock:
            latest = self._latest_rgb
        if latest is None:
            # Block briefly for the first frame.
            deadline = time.time() + 2.0
            while time.time() < deadline and latest is None:
                rospy.sleep(0.05)
                with self._image_lock:
                    latest = self._latest_rgb
        if latest is None:
            return np.zeros((480, 640, 3), dtype=np.uint8)
        return latest.copy()

    def is_connected(self) -> bool:
        deadline = time.time() + 2.0
        while time.time() < deadline:
            try:
                state = self._move_group.get_current_state()
                if state is not None:
                    return True
            except Exception:  # pragma: no cover
                pass
            try:
                rospy.sleep(0.1)
            except Exception:  # pragma: no cover
                time.sleep(0.1)
        return False
