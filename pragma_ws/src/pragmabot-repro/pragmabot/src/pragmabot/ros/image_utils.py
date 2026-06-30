"""ROS <-> NumPy image conversions.

Importable on Mac (no real ROS): the import guard sets ``ROS_AVAILABLE = False``
and the conversion functions raise a clear RuntimeError when called.
"""

from __future__ import annotations

# --- ROS import guard (per CLAUDE.md) ----------------------------------------
try:
    import rospy  # type: ignore  # noqa: F401
    from sensor_msgs.msg import CompressedImage, Image  # type: ignore  # noqa: F401

    ROS_AVAILABLE = True
except ImportError:
    ROS_AVAILABLE = False

try:
    from cv_bridge import CvBridge  # type: ignore

    _CV_BRIDGE_AVAILABLE = True
except ImportError:
    _CV_BRIDGE_AVAILABLE = False
# -----------------------------------------------------------------------------

import numpy as np


def _require_ros() -> None:
    if not ROS_AVAILABLE:
        raise RuntimeError(
            "ROS not available — install ROS Noetic + rospy + sensor_msgs to use this module."
        )


def _bridge():
    """Cached CvBridge instance, or None if cv_bridge is not installed."""
    if not _CV_BRIDGE_AVAILABLE:
        return None
    global _BRIDGE
    try:
        return _BRIDGE  # type: ignore[name-defined]
    except NameError:
        _BRIDGE = CvBridge()  # type: ignore[assignment]
        return _BRIDGE


def ros_image_to_numpy(msg) -> np.ndarray:
    """Convert a ``sensor_msgs/Image`` into NumPy.

    Return shapes by encoding:
        - rgb8 / bgr8 / mono8 → HxWx3 uint8 RGB image.
        - 16UC1 / mono16     → HxW float32 array in **meters** (raw mm × 0.001).
          This is the depth path: previously cv_bridge was asked for ``rgb8``
          which raises, so depth frames silently went missing. The float32
          output is what ``unproject_pixel`` expects.
    """
    _require_ros()
    bridge = _bridge()
    if bridge is not None:
        encoding = (msg.encoding or "").lower()
        if encoding in ("16uc1", "mono16"):
            arr = bridge.imgmsg_to_cv2(msg, desired_encoding="passthrough")
            return arr.astype(np.float32) * 0.001  # mm → meters
        if encoding in ("mono8", "8uc1"):
            arr = bridge.imgmsg_to_cv2(msg, desired_encoding="mono8")
            return np.stack([arr] * 3, axis=-1)
        # Force RGB for the remaining color encodings (rgb8 / bgr8 / etc).
        return bridge.imgmsg_to_cv2(msg, desired_encoding="rgb8")

    # Manual fallback — handle the most common encodings only.
    encoding = (msg.encoding or "").lower()
    height, width = int(msg.height), int(msg.width)
    if encoding in ("rgb8", "bgr8"):
        arr = np.frombuffer(msg.data, dtype=np.uint8).reshape(height, width, 3)
        if encoding == "bgr8":
            arr = arr[:, :, ::-1]
        return np.ascontiguousarray(arr)
    if encoding in ("mono8", "8uc1"):
        arr = np.frombuffer(msg.data, dtype=np.uint8).reshape(height, width)
        return np.stack([arr] * 3, axis=-1)
    if encoding in ("16uc1", "mono16"):
        arr = np.frombuffer(msg.data, dtype=np.uint16).reshape(height, width)
        return arr.astype(np.float32) * 0.001  # mm → meters
    raise ValueError(f"Unsupported image encoding without cv_bridge: {msg.encoding!r}")


def numpy_to_ros_image(array: np.ndarray, frame_id: str = "camera"):
    """Convert an HxWx3 RGB uint8 array into a ``sensor_msgs/Image`` (rgb8)."""
    _require_ros()
    if not isinstance(array, np.ndarray):
        raise TypeError(f"Expected np.ndarray, got {type(array).__name__}")
    if array.dtype != np.uint8:
        array = np.clip(array, 0, 255).astype(np.uint8)
    if array.ndim != 3 or array.shape[2] != 3:
        raise ValueError(f"Expected HxWx3, got shape {array.shape}")
    array = np.ascontiguousarray(array)

    bridge = _bridge()
    if bridge is not None:
        msg = bridge.cv2_to_imgmsg(array, encoding="rgb8")
        msg.header.frame_id = frame_id
        try:
            msg.header.stamp = rospy.Time.now()
        except Exception:  # pragma: no cover - tolerate no ros master in tests
            pass
        return msg

    from sensor_msgs.msg import Image  # type: ignore

    msg = Image()
    msg.header.frame_id = frame_id
    try:
        msg.header.stamp = rospy.Time.now()
    except Exception:  # pragma: no cover
        pass
    msg.height = int(array.shape[0])
    msg.width = int(array.shape[1])
    msg.encoding = "rgb8"
    msg.is_bigendian = 0
    msg.step = int(array.shape[1] * 3)
    msg.data = array.tobytes()
    return msg


def ros_compressed_to_numpy(msg) -> np.ndarray:
    """Convert a ``sensor_msgs/CompressedImage`` into an HxWx3 RGB uint8 array."""
    _require_ros()
    try:
        import cv2  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("OpenCV (cv2) required to decode CompressedImage") from exc

    np_arr = np.frombuffer(msg.data, dtype=np.uint8)
    bgr = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError("Failed to decode CompressedImage payload.")
    return bgr[:, :, ::-1].copy()  # BGR → RGB
