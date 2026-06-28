#!/usr/bin/env python3
"""Rosbag-replay image republisher.

Subscribes to the bag's RGB/depth topics and republishes them on the topics
the rest of the PragmaBot pipeline expects. Supports a click-to-republish
mode where forwarding only happens when an external trigger arrives — useful
for manual stepping through a recorded scene.
"""

from __future__ import annotations

# --- ROS import guard (per CLAUDE.md) ----------------------------------------
try:
    import rospy  # type: ignore
    from geometry_msgs.msg import Point  # type: ignore
    from sensor_msgs.msg import CompressedImage, Image  # type: ignore

    ROS_AVAILABLE = True
except ImportError:
    ROS_AVAILABLE = False
# -----------------------------------------------------------------------------

import logging
import sys
import threading
from pathlib import Path
from typing import Optional

# Add src/ to sys.path so this script runs under catkin or standalone.
_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from pragmabot.simple_config import load_config  # noqa: E402

logger = logging.getLogger(__name__)


def _require_ros() -> None:
    if not ROS_AVAILABLE:
        raise RuntimeError("ROS not available — image_republisher_node requires rospy.")


class ImageRepublisherNode:
    """Forward bag images onto pragmabot's expected topics, optionally gated by a trigger."""

    def __init__(self, config_path: Optional[str] = None) -> None:
        _require_ros()
        if not rospy.core.is_initialized():
            rospy.init_node("image_republisher_node", anonymous=True)

        if config_path is None:
            config_path = rospy.get_param(
                "~config_path", str(_SRC.parent / "config" / "config.yaml")
            )
        self.cfg = load_config(config_path)
        ros_cfg = self.cfg.ros

        # Click-gated mode: only republish ``max_per_trigger`` frames per click.
        self.max_per_trigger: int = int(rospy.get_param("~max_per_trigger", 1))
        self.always_forward: bool = bool(rospy.get_param("~always_forward", False))

        self.input_rgb_topic: str = rospy.get_param("~input_rgb_topic", "input/rgb")
        self.input_depth_topic: str = rospy.get_param("~input_depth_topic", "input/depth")
        self.click_topic: str = rospy.get_param(
            "~click_topic", str(ros_cfg.get("image_click_topic", "/pragmabot/image_click"))
        )

        self.output_rgb_topic: str = str(ros_cfg.get("republish_rgb_topic", "/pragmabot/camera/rgb"))
        self.output_depth_topic: str = str(
            ros_cfg.get("republish_depth_topic", "/pragmabot/camera/depth")
        )

        use_compressed = bool(ros_cfg.get("use_compressed_rgb", False))
        rgb_type = CompressedImage if use_compressed else Image

        # State
        self._rgb_remaining = 0
        self._depth_remaining = 0
        self._rgb_lock = threading.Lock()
        self._depth_lock = threading.Lock()

        # Pubs / subs
        self._rgb_pub = rospy.Publisher(self.output_rgb_topic, rgb_type, queue_size=1)
        self._depth_pub = rospy.Publisher(self.output_depth_topic, Image, queue_size=1)
        self._rgb_sub = rospy.Subscriber(self.input_rgb_topic, rgb_type, self._rgb_cb, queue_size=1)
        self._depth_sub = rospy.Subscriber(
            self.input_depth_topic, Image, self._depth_cb, queue_size=1
        )
        self._click_sub = rospy.Subscriber(self.click_topic, Point, self._click_cb, queue_size=1)

        logger.info(
            "ImageRepublisherNode: %s -> %s, %s -> %s (click=%s, always=%s)",
            self.input_rgb_topic,
            self.output_rgb_topic,
            self.input_depth_topic,
            self.output_depth_topic,
            self.click_topic,
            self.always_forward,
        )

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def _click_cb(self, _msg) -> None:
        rospy.loginfo("Republisher: trigger received, queuing %d frame(s).", self.max_per_trigger)
        with self._rgb_lock:
            self._rgb_remaining = self.max_per_trigger
        with self._depth_lock:
            self._depth_remaining = self.max_per_trigger

    def _rgb_cb(self, msg) -> None:
        if self.always_forward:
            self._rgb_pub.publish(msg)
            return
        with self._rgb_lock:
            if self._rgb_remaining > 0:
                self._rgb_pub.publish(msg)
                self._rgb_remaining -= 1

    def _depth_cb(self, msg) -> None:
        if self.always_forward:
            self._depth_pub.publish(msg)
            return
        with self._depth_lock:
            if self._depth_remaining > 0:
                self._depth_pub.publish(msg)
                self._depth_remaining -= 1

    def run(self) -> None:
        rospy.spin()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    ImageRepublisherNode().run()
    return 0


if __name__ == "__main__":  # pragma: no cover - ROS entry point
    sys.exit(main())
