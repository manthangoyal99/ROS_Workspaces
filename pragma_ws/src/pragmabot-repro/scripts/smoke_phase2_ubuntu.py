"""[UBUNTU] Phase 2 smoke — exercise the full ROS topic path end-to-end.

Requires a running roscore. Initializes a node, publishes a synthetic RGB
frame on the configured ros.rgb_topic, has SceneObserver consume it, then
runs one PragmaBot task using the observer as the observation source.
"""

from __future__ import annotations

import logging
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PKG_SRC = REPO_ROOT / "pragmabot" / "src"
if str(PKG_SRC) not in sys.path:
    sys.path.insert(0, str(PKG_SRC))

import numpy as np  # noqa: E402

try:
    import rospy  # type: ignore
    from sensor_msgs.msg import Image as ImageMsg  # type: ignore
except ImportError:
    print("ROS not available — this smoke script must run on Ubuntu with ROS Noetic.")
    sys.exit(2)

from pragmabot.pipeline import PragmaBot  # noqa: E402
from pragmabot.ros.image_utils import numpy_to_ros_image  # noqa: E402
from pragmabot.ros.scene_observer import SceneObserver  # noqa: E402
from pragmabot.simple_config import load_config  # noqa: E402


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    rospy.init_node("pragmabot_phase2_smoke", anonymous=True, disable_signals=True)

    cfg = load_config(REPO_ROOT / "pragmabot" / "config" / "config.yaml")
    cfg.vlm.backend = "stub"
    cfg.embeddings.backend = "stub"
    cfg.robot.backend = "stub"
    cfg.pipeline.max_steps = 2
    cfg.vlm.detector_mode = "complete_at:1"
    cfg.ros.use_compressed_rgb = False
    cfg.ros.rgb_topic = "/pragmabot_phase2_smoke/rgb"
    cfg.ros.depth_topic = ""  # disable depth for this smoke

    tmp = Path(tempfile.mkdtemp(prefix="pragmabot_phase2_ubuntu_"))
    cfg.memory.ltm_path = str(tmp / "ltm.csv")
    cfg.memory.embeddings_path = str(tmp / "ltm_embeddings.npy")

    observer = SceneObserver(cfg)

    # Publish one synthetic image and wait for the observer to see it.
    pub = rospy.Publisher(cfg.ros.rgb_topic, ImageMsg, queue_size=1)
    rospy.sleep(0.3)  # allow subscription to register
    rng = np.random.default_rng(0)
    payload = rng.integers(0, 256, size=(48, 64, 3), dtype=np.uint8)

    deadline = time.time() + 5.0
    while time.time() < deadline and not observer.is_receiving():
        pub.publish(numpy_to_ros_image(payload, frame_id="test"))
        rospy.sleep(0.1)

    rgb = observer.get_latest_rgb(timeout=3.0)
    assert rgb.shape == (48, 64, 3), f"unexpected RGB shape {rgb.shape}"
    print(f"SceneObserver delivered an image of shape {rgb.shape}.")

    bot = PragmaBot(cfg)
    bot.robot.set_observation_source(observer.get_latest_rgb)
    result = bot.run_task("touch the synthetic frame")
    print(f"Pipeline result: success={result['success']} steps={result['steps']}")
    assert result["success"] is True

    print("Phase 2 Ubuntu smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
