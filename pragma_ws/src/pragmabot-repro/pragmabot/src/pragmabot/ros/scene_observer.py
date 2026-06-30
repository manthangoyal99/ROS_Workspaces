"""Synchronized ROS camera subscriber.

Importable on Mac (no real ROS): instantiation raises RuntimeError at the
point ROS is actually needed, so module import alone is safe and the file
can be parsed/grep'd by tests.
"""

from __future__ import annotations

# --- ROS import guard (per CLAUDE.md) ----------------------------------------
try:
    import rospy  # type: ignore
    import message_filters  # type: ignore
    from sensor_msgs.msg import CompressedImage, Image  # type: ignore

    ROS_AVAILABLE = True
except ImportError:
    ROS_AVAILABLE = False
# -----------------------------------------------------------------------------

import logging
import threading
import time
from typing import Optional

import numpy as np
from omegaconf import DictConfig

from .image_utils import ros_compressed_to_numpy, ros_image_to_numpy

logger = logging.getLogger(__name__)


class SceneObserver:
    """Subscribes to RGB (and optional depth) ROS topics and exposes the latest frame."""

    def __init__(self, cfg: DictConfig) -> None:
        if not ROS_AVAILABLE:
            raise RuntimeError("ROS not available — SceneObserver requires rospy + sensor_msgs.")

        ros_cfg = cfg.ros if "ros" in cfg else cfg
        self.rgb_topic: str = str(ros_cfg.get("rgb_topic", "/camera/color/image_raw"))
        self.depth_topic: Optional[str] = ros_cfg.get("depth_topic")
        self.use_compressed_rgb: bool = bool(ros_cfg.get("use_compressed_rgb", False))
        self.image_timeout_sec: float = float(ros_cfg.get("image_timeout_sec", 5.0))

        self._lock = threading.Lock()
        self._latest_rgb: Optional[np.ndarray] = None
        self._latest_depth: Optional[np.ndarray] = None
        self._latest_stamp: float = 0.0

        rgb_msg_type = CompressedImage if self.use_compressed_rgb else Image
        self.rgb_sub = rospy.Subscriber(self.rgb_topic, rgb_msg_type, self._rgb_cb, queue_size=1)
        if self.depth_topic:
            self.depth_sub = rospy.Subscriber(self.depth_topic, Image, self._depth_cb, queue_size=1)
        else:
            self.depth_sub = None

        logger.info(
            "SceneObserver subscribed: rgb=%s (compressed=%s) depth=%s",
            self.rgb_topic,
            self.use_compressed_rgb,
            self.depth_topic,
        )

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def _rgb_cb(self, msg) -> None:
        try:
            if self.use_compressed_rgb:
                arr = ros_compressed_to_numpy(msg)
            else:
                arr = ros_image_to_numpy(msg)
        except Exception as exc:  # pragma: no cover - runtime defensive
            logger.error("Failed to decode RGB image: %s", exc)
            return
        with self._lock:
            self._latest_rgb = arr
            self._latest_stamp = time.time()

    def _depth_cb(self, msg) -> None:
        try:
            arr = ros_image_to_numpy(msg)
        except Exception as exc:  # pragma: no cover
            logger.error("Failed to decode depth image: %s", exc)
            return
        with self._lock:
            self._latest_depth = arr

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_latest_rgb(self, timeout: Optional[float] = None) -> np.ndarray:
        """Block until a new RGB image is available, or raise on timeout."""
        timeout = float(timeout if timeout is not None else self.image_timeout_sec)
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                latest = self._latest_rgb
            if latest is not None:
                return latest.copy()
            time.sleep(0.02)
        raise TimeoutError(
            f"No RGB image received on {self.rgb_topic!r} within {timeout:.1f}s"
        )

    def get_latest_depth(self, timeout: Optional[float] = None) -> Optional[np.ndarray]:
        """Return the most recent depth frame, or None if no depth subscription."""
        if self.depth_sub is None:
            return None
        timeout = float(timeout if timeout is not None else self.image_timeout_sec)
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                latest = self._latest_depth
            if latest is not None:
                return latest.copy()
            time.sleep(0.02)
        return None

    def is_receiving(self) -> bool:
        """True if an RGB frame has arrived in the last 2 seconds."""
        with self._lock:
            stamp = self._latest_stamp
        return stamp > 0.0 and (time.time() - stamp) < 2.0
