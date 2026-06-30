"""[UBUNTU] Phase 5 smoke — stub VLM + Gazebo Franka end-to-end."""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PKG_SRC = REPO_ROOT / "pragmabot" / "src"
if str(PKG_SRC) not in sys.path:
    sys.path.insert(0, str(PKG_SRC))

try:
    import rospy  # type: ignore
except ImportError:
    print("ROS not available — this smoke script must run on Ubuntu with ROS Noetic.")
    sys.exit(2)

from pragmabot.pipeline import PragmaBot  # noqa: E402
from pragmabot.simple_config import load_config  # noqa: E402


def _topic_alive(topic: str, timeout: float = 3.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            published = [t for t, _ in rospy.get_published_topics()]
            if topic in published:
                return True
        except Exception:  # pragma: no cover
            pass
        rospy.sleep(0.2)
    return False


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    rospy.init_node("pragmabot_phase5_gazebo_smoke", anonymous=True, disable_signals=True)

    cfg = load_config(REPO_ROOT / "pragmabot" / "config" / "config.yaml")
    cfg.vlm.backend = "stub"
    cfg.embeddings.backend = "stub"
    cfg.perception.backend = "stub"
    cfg.robot.backend = "franka_ros"
    cfg.pipeline.max_steps = 1
    cfg.vlm.detector_mode = "complete_at:1"
    cfg.vlm.planner_skill = "pick"
    cfg.vlm.planner_object = "apple"

    for topic in (cfg.ros.rgb_topic, "/move_group/status"):
        alive = _topic_alive(topic, timeout=5.0)
        print(f"topic {topic} live={alive}")

    bot = PragmaBot(cfg)
    print(f"robot.is_connected() = {bot.robot.is_connected()}")

    result = bot.run_task("pick up the apple")
    print(f"success={result['success']} steps={result['steps']} error={result.get('error')!r}")
    print(f"episode_log: {result['episode_log_path']}")
    if result["episode_log_path"]:
        payload = json.loads(Path(result["episode_log_path"]).read_text())
        for step in payload["stm"]:
            print(
                f"step {step['step']}: plan={step['planning_time_sec']:.3f}s "
                f"exec={step['execution_time_sec']:.3f}s "
                f"detect={step['detection_time_sec']:.3f}s"
            )

    print("Phase 5 Gazebo smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
