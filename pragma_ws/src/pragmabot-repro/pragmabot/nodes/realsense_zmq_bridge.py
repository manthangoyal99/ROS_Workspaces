#!/usr/bin/env python3
"""RealSense → FoundationPose ZMQ Bridge Node.

A ROS 1 (Noetic) node that captures live RGB-D frames from an Intel RealSense
camera, compresses them on-the-fly, transmits them to a remote GPU server
running FoundationPose inside Docker via ZeroMQ, and visualises the returned
6-DOF pose as a projected 3-D bounding box overlaid on the local video feed.

Network protocol
────────────────
  Client (REQ) ──TCP:5555──▸ Server (REP)
  Payload out  : msgpack({rgb_jpg, depth_png, K})
  Payload in   : msgpack({pose: 4×4, bbox: 8×3})   OR   msgpack({error: str})

Usage
─────
  # 1. Start the RealSense driver (separate terminal)
  roslaunch realsense2_camera rs_camera.launch align_depth:=true

  # 2. Run this node
  rosrun pragmabot realsense_zmq_bridge.py _server_ip:=10.72.18.159

  # OR via the provided launch file
  roslaunch pragmabot foundationpose_tracking.launch server_ip:=10.72.18.159

Edge-case handling
──────────────────
  • Skips processing if depth or intrinsics haven't arrived yet.
  • ZMQ recv() timeout (default 5 s) with automatic socket reconnect to
    prevent indefinite blocking on server loss.
  • cv_bridge conversion errors are caught and throttle-logged.
  • rospy.on_shutdown destroys OpenCV windows and tears down ZMQ context.
  • REQ/REP lock-step violation after a timeout is handled by socket
    teardown + recreation (see _reconnect_zmq).
  • In-flight guard prevents re-entrant ZMQ sends when the colour callback
    fires faster than the server round-trip time.
"""

from __future__ import annotations

import logging
import sys
import threading
from typing import Optional

import cv2
import numpy as np

# ── ROS imports (guarded for non-ROS environments) ──────────────────────────
try:
    import rospy
    from cv_bridge import CvBridge, CvBridgeError
    from sensor_msgs.msg import CameraInfo, Image
    from std_msgs.msg import String
    import tf.transformations as tf_trans
    import tf2_ros
    
    from pragmabot.simple_config import load_config
    from pragmabot.perception.grounded_sam import GroundedSAMPerception

    ROS_AVAILABLE = True
except ImportError:
    ROS_AVAILABLE = False

# ── ZMQ + serialisation ────────────────────────────────────────────────────
import msgpack
import msgpack_numpy as m
import zmq

# Patch msgpack so numpy arrays are auto-(de)serialised.
m.patch()

logger = logging.getLogger("realsense_zmq_bridge")

# ── 3-D bounding-box edge list (12 edges of a cuboid) ──────────────────────
# Corner ordering follows the trimesh oriented_bounds convention:
#   0-1, 1-2, 2-3, 3-0  (bottom face)
#   4-5, 5-6, 6-7, 7-4  (top face)
#   0-4, 1-5, 2-6, 3-7  (verticals)
BBOX_EDGES = [
    (0, 1), (1, 2), (2, 3), (3, 0),
    (4, 5), (5, 6), (6, 7), (7, 4),
    (0, 4), (1, 5), (2, 6), (3, 7),
]

# Colour palette for rendering (BGR)
EDGE_COLOR = (0, 255, 0)      # bright green
EDGE_THICKNESS = 2


class RealSenseZMQBridge:
    """Bridges local RealSense RGB-D to a remote FoundationPose server."""

    # ── construction ────────────────────────────────────────────────────────

    def __init__(self) -> None:
        if not ROS_AVAILABLE:
            raise RuntimeError(
                "rospy is not importable – run inside a ROS 1 workspace."
            )

        rospy.init_node("realsense_zmq_bridge", anonymous=False)

        # ── configurable parameters (set via rosparam / launch file) ────────
        server_ip: str = rospy.get_param("~server_ip", "10.72.18.159")
        server_port: int = int(rospy.get_param("~server_port", 5555))
        self._jpeg_quality: int = int(rospy.get_param("~jpeg_quality", 80))
        self._zmq_timeout_ms: int = int(rospy.get_param("~zmq_timeout_ms", 5000))
        camera_name: str = rospy.get_param("~camera_name", "camera_base_link")
        self._object_names: list[str] = rospy.get_param("~object_names", ["mustard0"])
        self._base_frame: str = rospy.get_param("~base_frame", "panda_link0")
        self._server_endpoint = f"tcp://{server_ip}:{server_port}"

        # ── TF Listener ─────────────────────────────────────────────────────
        self._tf_buffer = tf2_ros.Buffer()
        self._tf_listener = tf2_ros.TransformListener(self._tf_buffer)

        # ── ZMQ context + REQ socket ────────────────────────────────────────
        self._zmq_ctx = zmq.Context()
        self._zmq_sock: zmq.Socket = self._zmq_ctx.socket(zmq.REQ)
        # Linger 0 – discard unsent data on close so shutdown is instant.
        self._zmq_sock.setsockopt(zmq.LINGER, 0)
        # Receive timeout protects against indefinite blocking if the server
        # goes away mid-session.
        self._zmq_sock.setsockopt(zmq.RCVTIMEO, self._zmq_timeout_ms)
        self._zmq_sock.connect(self._server_endpoint)
        rospy.loginfo("ZMQ REQ socket connected → %s", self._server_endpoint)

        # ── Initialize Grounded SAM ──
        try:
            rospy.loginfo("Loading Grounded SAM models (this may take 10-15 seconds)...")
            config_path = "/home/ravi/pragma_ws/src/pragmabot-repro/pragmabot/config/config_ubuntu.yaml"
            cfg = load_config(config_path)
            self.perception = GroundedSAMPerception(cfg)
            self._is_first_frame = True
            rospy.loginfo("Grounded SAM successfully loaded.")
        except Exception as e:
            rospy.logerr("Failed to load Grounded SAM: %s", e)
            self.perception = None
            self._is_first_frame = False

        # ── CV bridge ───────────────────────────────────────────────────────
        self._bridge = CvBridge()

        # ── thread-safe frame cache ─────────────────────────────────────────
        self._depth_frame: Optional[np.ndarray] = None
        self._depth_lock = threading.Lock()

        self._K: Optional[np.ndarray] = None           # 3×3 intrinsics
        self._dist_coeffs: Optional[np.ndarray] = None # distortion (may be zeros)
        self._intrinsics_lock = threading.Lock()
        self._intrinsics_received = False

        # ── flag: is a ZMQ request in-flight? ───────────────────────────────
        # Prevents re-entrant sends when the colour callback fires faster
        # than the round-trip time.  REQ/REP is strictly lock-step.
        self._request_in_flight = False
        self._flight_lock = threading.Lock()

        # ── ROS subscribers ─────────────────────────────────────────────────
        self._sub_info = rospy.Subscriber(
            f"/{camera_name}/color/camera_info", CameraInfo,
            self._cb_camera_info, queue_size=1,
        )
        self._sub_depth = rospy.Subscriber(
            f"/{camera_name}/aligned_depth_to_color/image_raw", Image,
            self._cb_depth, queue_size=1,
        )
        self._sub_color = rospy.Subscriber(
            f"/{camera_name}/color/image_raw", Image,
            self._cb_color, queue_size=1,
        )

        # ── ROS publishers ──────────────────────────────────────────────────
        self._pub_tracking = rospy.Publisher(
            "~tracking_data", String, queue_size=1,
        )
        self._pub_tracking_base = rospy.Publisher(
            "~tracking_data_base", String, queue_size=1,
        )

        # ── shutdown hook ───────────────────────────────────────────────────
        rospy.on_shutdown(self._shutdown)

        rospy.loginfo(
            "RealSenseZMQBridge initialised "
            "(server=%s, jpeg_q=%d, timeout=%d ms)",
            self._server_endpoint, self._jpeg_quality, self._zmq_timeout_ms,
        )

    # ────────────────────────────────────────────────────────────────────────
    # ROS Callbacks
    # ────────────────────────────────────────────────────────────────────────

    def _cb_camera_info(self, msg: CameraInfo) -> None:
        """Cache the 3×3 camera intrinsic matrix K.

        Only processes the first message — intrinsics are static for a given
        RealSense stream configuration.
        """
        if self._intrinsics_received:
            return
        with self._intrinsics_lock:
            # msg.K is a flat row-major 9-element tuple:
            #   [fx, 0, cx, 0, fy, cy, 0, 0, 1]
            self._K = np.array(msg.K, dtype=np.float64).reshape(3, 3)
            self._dist_coeffs = np.array(msg.D, dtype=np.float64)
            self._intrinsics_received = True
        rospy.loginfo("Camera intrinsics received:\n%s", self._K)

    def _cb_depth(self, msg: Image) -> None:
        """Cache the latest aligned depth image (16UC1, millimetres)."""
        try:
            depth = self._bridge.imgmsg_to_cv2(
                msg, desired_encoding="passthrough"
            )
        except CvBridgeError as exc:
            rospy.logwarn_throttle(5.0, "Depth cv_bridge error: %s", exc)
            return
        with self._depth_lock:
            self._depth_frame = depth

    def _cb_color(self, msg: Image) -> None:
        """Main processing trigger — runs on every new colour frame."""

        # Debug: Check if the callback is firing at all
        if not hasattr(self, "_first_color_received"):
            rospy.loginfo("DEBUG: First color image received from ROS topic!")
            self._first_color_received = True

        # ── guard: skip if we haven't received depth / intrinsics yet ──────
        with self._intrinsics_lock:
            if self._K is None:
                rospy.logwarn_throttle(5.0, "Waiting for camera intrinsics…")
                return
            K = self._K.copy()
            dist_coeffs = self._dist_coeffs.copy()

        with self._depth_lock:
            if self._depth_frame is None:
                rospy.logwarn_throttle(5.0, "Waiting for depth frame…")
                return
            depth = self._depth_frame.copy()

        # ── guard: skip if a request is already in-flight ──────────────────
        with self._flight_lock:
            if self._request_in_flight:
                return
            self._request_in_flight = True

        try:
            self._process_frame(msg, depth, K, dist_coeffs)
        finally:
            with self._flight_lock:
                self._request_in_flight = False

    # ────────────────────────────────────────────────────────────────────────
    # Core pipeline step
    # ────────────────────────────────────────────────────────────────────────

    def _process_frame(
        self,
        color_msg: Image,
        depth: np.ndarray,
        K: np.ndarray,
        dist_coeffs: np.ndarray,
    ) -> None:
        """Compress → send → receive → project → draw.  One full cycle."""

        # ── convert colour ROS message → OpenCV BGR ────────────────────────
        try:
            color_bgr = self._bridge.imgmsg_to_cv2(
                color_msg, desired_encoding="bgr8"
            )
        except CvBridgeError as exc:
            rospy.logwarn_throttle(5.0, "Color cv_bridge error: %s", exc)
            return

        # ── compress images for network transfer ───────────────────────────
        #  • JPEG for colour — lossy but fast and small (~10-30 KB @q80)
        #  • PNG for depth — lossless required for metric accuracy
        ok_jpg, jpg_buf = cv2.imencode(
            ".jpg", color_bgr,
            [cv2.IMWRITE_JPEG_QUALITY, self._jpeg_quality],
        )
        ok_png, png_buf = cv2.imencode(".png", depth)
        if not ok_jpg or not ok_png:
            rospy.logwarn_throttle(
                5.0, "Image compression failed — skipping frame."
            )
            return

        # ── run SAM detection on first frame ───────────────────────────────
        sam_masks = {}
        if self._is_first_frame and self.perception is not None:
            rospy.loginfo("First frame detected. Running Grounded SAM for masks...")
            try:
                color_rgb = cv2.cvtColor(color_bgr, cv2.COLOR_BGR2RGB)
                results = self.perception.detect(rgb=color_rgb, queries=self._object_names, depth=depth)
                for obj in results.objects:
                    if obj.mask is not None:
                        # Convert boolean mask to uint8 for safe msgpack serialization
                        sam_masks[obj.name] = obj.mask.astype(np.uint8)
                rospy.loginfo("Grounded SAM generated masks for: %s", list(sam_masks.keys()))
                self._is_first_frame = False
            except Exception as e:
                rospy.logerr("Grounded SAM detection failed: %s", e)
                self._is_first_frame = False

        # ── build payload ──────────────────────────────────────────────────
        payload = msgpack.packb({
            "rgb_jpg":   jpg_buf.tobytes(),
            "depth_png": png_buf.tobytes(),
            "K":         K,                 # numpy array, auto-serialised
            "object_names": self._object_names,
            "masks": sam_masks,
        })

        # ── send / receive via ZMQ ─────────────────────────────────────────
        try:
            rospy.loginfo_throttle(5.0, "DEBUG: Sending payload to ZMQ server...")
            self._zmq_sock.send(payload)
            rospy.loginfo_throttle(5.0, "DEBUG: Waiting for ZMQ reply from server...")
            reply_raw = self._zmq_sock.recv()
            rospy.loginfo_throttle(5.0, "DEBUG: Received ZMQ reply from server!")
        except zmq.Again:
            # Receive timed out — the server didn't respond in time.
            rospy.logwarn_throttle(
                5.0,
                "ZMQ recv timeout (%d ms) — server may be overloaded "
                "or unreachable. Reconnecting…",
                self._zmq_timeout_ms,
            )
            self._reconnect_zmq()
            return
        except zmq.ZMQError as exc:
            rospy.logerr_throttle(
                5.0, "ZMQ error: %s — reconnecting", exc
            )
            self._reconnect_zmq()
            return

        # ── deserialise reply ──────────────────────────────────────────────
        try:
            reply = msgpack.unpackb(reply_raw, raw=False)
        except Exception as exc:
            rospy.logwarn_throttle(5.0, "msgpack unpack error: %s", exc)
            return

        if "error" in reply:
            rospy.logwarn_throttle(5.0, "Server error: %s", reply["error"])
            return

        poses_dict = reply.get("poses", {})
        bboxes_dict = reply.get("bboxes", {})

        # ── Publish ROS topics ──────────────────────────────────────────
        self._publish_topics(poses_dict, bboxes_dict, color_msg.header.stamp)

        # ── draw 12 cuboid edges on the local (uncompressed) frame ─────────
        vis = color_bgr.copy()

        y_offset = 25
        for name in poses_dict:
            bbox_3d = np.asarray(bboxes_dict[name], dtype=np.float64)
            pose = np.asarray(poses_dict[name], dtype=np.float64)

            # ── project 3-D corners → 2-D pixel coordinates ───────────────────
            pts_2d = self._project_points(bbox_3d, K, dist_coeffs)
            if pts_2d is not None:
                for i, j in BBOX_EDGES:
                    pt1 = tuple(pts_2d[i].astype(int))
                    pt2 = tuple(pts_2d[j].astype(int))
                    cv2.line(vis, pt1, pt2, EDGE_COLOR, EDGE_THICKNESS, cv2.LINE_AA)

            # ── HUD overlay: translation component of pose ────────────────────
            tx, ty, tz = pose[:3, 3]
            cv2.putText(
                vis,
                f"{name}: t=[{tx:.3f}, {ty:.3f}, {tz:.3f}] m",
                (10, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                (255, 255, 255), 1, cv2.LINE_AA,
            )
            y_offset += 25

        # Only show the GUI window when an X display is actually available
        # (running over SSH without X-forwarding would otherwise abort the
        # process via Qt). Set the env var PRAGMA_BRIDGE_GUI=1 to force-enable.
        import os as _os
        if _os.environ.get("PRAGMA_BRIDGE_GUI", "").strip() == "1" or (
            _os.environ.get("DISPLAY", "").strip()
            and _os.environ.get("QT_QPA_PLATFORM", "").strip() != "offscreen"
        ):
            try:
                cv2.imshow("FoundationPose Tracking", vis)
                cv2.waitKey(1)
            except cv2.error as _exc:
                rospy.logwarn_throttle(
                    30.0, f"cv2.imshow failed (headless?): {_exc}"
                )

    # ────────────────────────────────────────────────────────────────────────
    # Helper methods
    # ────────────────────────────────────────────────────────────────────────

    def _publish_topics(self, poses_dict: dict, bboxes_dict: dict, stamp: rospy.Time) -> None:
        """Publish the tracking data as a JSON string."""
        import json
        
        camera_frame_id = f"{rospy.get_param('~camera_name', 'camera_base')}_color_optical_frame"
        
        tracking_data = {
            "header": {
                "stamp_secs": stamp.secs,
                "stamp_nsecs": stamp.nsecs,
                "frame_id": camera_frame_id
            },
            "objects": {}
        }
        
        tracking_data_base = {
            "header": {
                "stamp_secs": stamp.secs,
                "stamp_nsecs": stamp.nsecs,
                "frame_id": self._base_frame
            },
            "objects": {}
        }
        
        # Attempt to get transform from camera frame to base frame
        trans_cam_to_base = None
        try:
            trans_cam_to_base = self._tf_buffer.lookup_transform(
                self._base_frame, camera_frame_id, rospy.Time(0), rospy.Duration(0.1)
            )
            # Create a 4x4 transformation matrix
            trans = trans_cam_to_base.transform.translation
            rot = trans_cam_to_base.transform.rotation
            tf_mat = tf_trans.quaternion_matrix([rot.x, rot.y, rot.z, rot.w])
            tf_mat[:3, 3] = [trans.x, trans.y, trans.z]
        except (tf2_ros.LookupException, tf2_ros.ConnectivityException, tf2_ros.ExtrapolationException) as e:
            rospy.logwarn_throttle(5.0, "TF lookup failed from %s to %s: %s", camera_frame_id, self._base_frame, e)
        
        for name in poses_dict:
            pose = np.asarray(poses_dict[name], dtype=np.float64)
            bbox = np.asarray(bboxes_dict[name], dtype=np.float64)
            
            rot_mat = np.eye(4)
            rot_mat[:3, :3] = pose[:3, :3]
            q = tf_trans.quaternion_from_matrix(rot_mat)
            
            obj_data = {
                "pose": {
                    "position": {"x": pose[0, 3], "y": pose[1, 3], "z": pose[2, 3]},
                    "orientation": {"x": q[0], "y": q[1], "z": q[2], "w": q[3]}
                },
                "bbox": bbox.flatten().tolist()
            }
            
            tracking_data["objects"][name] = obj_data
            
            # If TF is available, compute bounding box and pose in base frame
            if trans_cam_to_base is not None:
                # bbox is Nx3. Convert to Nx4 homogeneous
                bbox_homo = np.hstack((bbox, np.ones((bbox.shape[0], 1))))
                bbox_base = (tf_mat @ bbox_homo.T).T[:, :3]
                
                # Transform the pose as well
                pose_base = tf_mat @ pose
                q_base = tf_trans.quaternion_from_matrix(pose_base)
                
                tracking_data_base["objects"][name] = {
                    "pose": {
                        "position": {"x": pose_base[0, 3], "y": pose_base[1, 3], "z": pose_base[2, 3]},
                        "orientation": {"x": q_base[0], "y": q_base[1], "z": q_base[2], "w": q_base[3]}
                    },
                    "bbox": bbox_base.flatten().tolist()
                }
            
        json_str = json.dumps(tracking_data)
        msg = String()
        msg.data = json_str
        self._pub_tracking.publish(msg)
        
        if trans_cam_to_base is not None:
            json_str_base = json.dumps(tracking_data_base)
            msg_base = String()
            msg_base.data = json_str_base
            self._pub_tracking_base.publish(msg_base)

    @staticmethod
    def _project_points(
        pts_3d: np.ndarray,
        K: np.ndarray,
        dist_coeffs: np.ndarray,
    ) -> Optional[np.ndarray]:
        """Project Nx3 camera-frame 3-D points → Nx2 pixel coordinates.

        Uses cv2.projectPoints with identity rotation/translation because
        the points are *already* in the camera coordinate frame (the server
        transforms model-space corners into camera space before replying).
        """
        rvec = np.zeros(3, dtype=np.float64)
        tvec = np.zeros(3, dtype=np.float64)
        try:
            pts_2d, _ = cv2.projectPoints(
                pts_3d.reshape(-1, 1, 3), rvec, tvec, K, dist_coeffs,
            )
            return pts_2d.reshape(-1, 2)
        except cv2.error as exc:
            rospy.logwarn_throttle(5.0, "projectPoints failed: %s", exc)
            return None

    def _reconnect_zmq(self) -> None:
        """Tear down and recreate the ZMQ REQ socket.

        REQ/REP is strictly lock-step: if a recv() times out *after* a
        send(), the socket enters an invalid state (expecting a reply that
        will never arrive).  The only recovery is to destroy and recreate
        the socket.
        """
        rospy.loginfo("Reconnecting ZMQ socket → %s", self._server_endpoint)
        try:
            self._zmq_sock.close()
        except zmq.ZMQError:
            pass
        self._zmq_sock = self._zmq_ctx.socket(zmq.REQ)
        self._zmq_sock.setsockopt(zmq.LINGER, 0)
        self._zmq_sock.setsockopt(zmq.RCVTIMEO, self._zmq_timeout_ms)
        self._zmq_sock.connect(self._server_endpoint)

    def _shutdown(self) -> None:
        """Graceful cleanup on ROS shutdown (Ctrl-C or rosnode kill)."""
        rospy.loginfo("Shutting down RealSenseZMQBridge…")
        cv2.destroyAllWindows()
        try:
            self._zmq_sock.close()
            self._zmq_ctx.term()
        except zmq.ZMQError:
            pass

    # ── spin ────────────────────────────────────────────────────────────────

    def run(self) -> None:
        """Block until ROS shutdown."""
        rospy.spin()


# ── entry point ─────────────────────────────────────────────────────────────

def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s %(message)s",
    )
    try:
        RealSenseZMQBridge().run()
    except rospy.ROSInterruptException:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
