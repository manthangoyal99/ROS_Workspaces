"""Phase 5 Ubuntu integration tests — full stack, slow."""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pytest

try:
    import rospy  # type: ignore  # noqa: F401
    import moveit_commander  # type: ignore  # noqa: F401

    ROS_AVAILABLE = True
except ImportError:
    ROS_AVAILABLE = False

pytestmark = [
    pytest.mark.skipif(not ROS_AVAILABLE, reason="ROS not available"),
    pytest.mark.integration,
]


REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "pragmabot" / "config" / "config.yaml"


@pytest.fixture(scope="module")
def cfg(tmp_path_factory):
    from pragmabot.simple_config import load_config

    config = load_config(CONFIG_PATH)
    tmp = tmp_path_factory.mktemp("phase5")
    config.memory.ltm_path = str(tmp / "ltm.csv")
    config.memory.embeddings_path = str(tmp / "ltm_embeddings.npy")
    config.logging.log_dir = str(tmp / "logs")
    config.vlm.backend = "stub"
    config.embeddings.backend = "stub"
    config.perception.backend = "stub"
    config.robot.backend = "franka_ros"
    config.pipeline.max_steps = 2
    config.vlm.detector_mode = "complete_at:1"
    return config


def test_full_node_instantiates(cfg):
    import sys
    sys.path.insert(0, str(REPO_ROOT / "pragmabot" / "nodes"))
    import pragmabot_node  # type: ignore

    node = pragmabot_node.PragmaBotNode(str(CONFIG_PATH))
    assert node is not None


def test_scene_observer_to_pipeline(cfg):
    """SceneObserver feeds an image into the pipeline."""
    from pragmabot.pipeline import PragmaBot
    from pragmabot.ros.image_utils import numpy_to_ros_image
    from pragmabot.ros.scene_observer import SceneObserver
    from sensor_msgs.msg import Image as ImageMsg  # type: ignore

    # ROS node init is owned by tests/ubuntu/conftest.py::ros_node.

    cfg.ros.rgb_topic = "/pragmabot_phase5/rgb"
    cfg.ros.depth_topic = ""
    cfg.robot.backend = "stub"  # don't move the arm in this unit
    observer = SceneObserver(cfg)
    pub = rospy.Publisher(cfg.ros.rgb_topic, ImageMsg, queue_size=1)
    rng = np.random.default_rng(0)
    deadline = time.time() + 5.0
    payload = rng.integers(0, 256, size=(48, 64, 3), dtype=np.uint8)
    while time.time() < deadline and not observer.is_receiving():
        pub.publish(numpy_to_ros_image(payload, frame_id="test"))
        rospy.sleep(0.1)
    rgb = observer.get_latest_rgb(timeout=3.0)
    assert rgb.shape == (48, 64, 3)

    bot = PragmaBot(cfg)
    bot.robot.set_observation_source(observer.get_latest_rgb)
    result = bot.run_task("touch the test frame")
    assert "success" in result


def test_episode_log_written(cfg, tmp_path):
    from pragmabot.pipeline import PragmaBot

    cfg.robot.backend = "stub"
    cfg.logging.log_dir = str(tmp_path / "ep")
    bot = PragmaBot(cfg)
    result = bot.run_task("pick up the apple")
    assert result["episode_log_path"]
    payload = json.loads(Path(result["episode_log_path"]).read_text())
    assert payload["instruction"] == "pick up the apple"


def test_ltm_persists_across_node_restart(cfg, tmp_path):
    from pragmabot.memory.embeddings import get_embedder
    from pragmabot.memory.memory_manager import MemoryManager
    from pragmabot.pipeline import PragmaBot

    cfg.robot.backend = "stub"
    cfg.memory.ltm_path = str(tmp_path / "persist.csv")
    cfg.memory.embeddings_path = str(tmp_path / "persist.npy")

    bot1 = PragmaBot(cfg)
    bot1.run_task("pick up the apple")
    assert len(bot1.memory) >= 1

    embedder = get_embedder(cfg)
    mem2 = MemoryManager(cfg, embedder)
    assert len(mem2) == len(bot1.memory)


def test_workspace_limit_blocks_motion(cfg):
    """An out-of-bounds target must not move the arm and must return False."""
    from pragmabot.robot.franka_ros import FrankaRobot

    cfg.robot.backend = "franka_ros"
    robot = FrankaRobot(cfg)
    assert robot._check_workspace_limits(np.array([5.0, 0.0, 0.3])) is False
    out = robot.execute_pick("ghost", target_position_3d=np.array([5.0, 0.0, 0.3]))
    assert out is False


def test_full_task_stub_vlm_real_robot(cfg):
    """Stub VLM + stub perception + real Gazebo Franka — pipeline runs to completion."""
    from pragmabot.pipeline import PragmaBot

    cfg.robot.backend = "franka_ros"
    cfg.pipeline.max_steps = 1
    cfg.vlm.detector_mode = "complete_at:1"
    cfg.vlm.planner_object = "apple"
    cfg.vlm.planner_skill = "pick"
    bot = PragmaBot(cfg)
    result = bot.run_task("pick up the apple")
    assert "stm" in result
    assert result["episode_log_path"]


def test_gradio_launches(tmp_path):
    """The Gradio UI must launch on the configured port and accept a connection."""
    import sys

    sys.path.insert(0, str(REPO_ROOT / "pragmabot" / "nodes"))
    import pragmabot_node  # type: ignore

    node = pragmabot_node.PragmaBotNode(str(CONFIG_PATH))
    demo = node._build_ui()
    host = "127.0.0.1"
    port = int(node._cfg.gradio.port) + 1  # avoid clashing with the live UI
    demo.launch(server_name=host, server_port=port, prevent_thread_lock=True)
    try:
        import requests  # type: ignore

        r = requests.get(f"http://{host}:{port}/", timeout=5)
        assert r.status_code in (200, 302)
    finally:
        demo.close()
