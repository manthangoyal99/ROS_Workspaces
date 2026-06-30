"""Phase 2 Ubuntu (ROS Noetic) smoke tests.

Skipped on any machine without rospy + sensor_msgs available.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# Module-level skip guard.
try:
    import rospy  # type: ignore  # noqa: F401
    import sensor_msgs  # type: ignore  # noqa: F401
except ImportError:
    pytest.skip("ROS not available", allow_module_level=True)


import numpy as np  # noqa: E402

from pragmabot.pipeline import PragmaBot  # noqa: E402
from pragmabot.ros.image_utils import numpy_to_ros_image, ros_image_to_numpy  # noqa: E402
from pragmabot.ros.scene_observer import SceneObserver  # noqa: E402
from pragmabot.simple_config import load_config  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[2]
PKG_ROOT = REPO_ROOT / "pragmabot"
CONFIG_PATH = PKG_ROOT / "config" / "config.yaml"


# ROS init is owned by the session-scoped fixture in tests/ubuntu/conftest.py.
def _maybe_init_node() -> None:
    """Kept as a no-op for backwards compatibility — see conftest.py::ros_node."""


# ---------------------------------------------------------------------------
# Static / pure
# ---------------------------------------------------------------------------


def test_config_has_ros_section():
    cfg = load_config(CONFIG_PATH)
    assert "ros" in cfg
    for key in ("rgb_topic", "depth_topic", "image_timeout_sec", "rosbag_replay"):
        assert key in cfg.ros


def test_package_xml_exists():
    import xml.etree.ElementTree as ET

    path = PKG_ROOT / "package.xml"
    assert path.exists()
    ET.parse(path)


@pytest.mark.parametrize(
    "name",
    [
        "launch_pragmabot.launch",
        "replay_rosbag.launch",
        "manage_memory.launch",
        "record_rosbag.launch",
    ],
)
def test_launch_files_exist(name):
    assert (PKG_ROOT / "launch" / name).exists()


# ---------------------------------------------------------------------------
# Conversion roundtrip — does NOT require a running ROS master
# ---------------------------------------------------------------------------


def test_ros_image_utils_roundtrip():
    rng = np.random.default_rng(0)
    arr = rng.integers(0, 256, size=(24, 32, 3), dtype=np.uint8)
    msg = numpy_to_ros_image(arr, frame_id="camera_test")
    out = ros_image_to_numpy(msg)
    assert out.shape == arr.shape
    assert out.dtype == np.uint8
    assert np.array_equal(out, arr)


# ---------------------------------------------------------------------------
# Node-level instantiation (requires roscore)
# ---------------------------------------------------------------------------


def test_scene_observer_init():
    _maybe_init_node()
    cfg = load_config(CONFIG_PATH)
    obs = SceneObserver(cfg)
    assert obs.rgb_topic == cfg.ros.rgb_topic


def test_image_republisher_init():
    _maybe_init_node()
    # Import lazily so the module is only loaded when ROS is available.
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "pragmabot_image_republisher_node",
        str(PKG_ROOT / "nodes" / "image_republisher_node.py"),
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    node = mod.ImageRepublisherNode()
    assert node.output_rgb_topic
    assert node.output_depth_topic


# ---------------------------------------------------------------------------
# Pipeline driven by an injected observation source
# ---------------------------------------------------------------------------


def test_pipeline_with_ros_observation_source(tmp_path):
    cfg = load_config(CONFIG_PATH)
    cfg.memory.ltm_path = str(tmp_path / "ltm.csv")
    cfg.memory.embeddings_path = str(tmp_path / "ltm_embeddings.npy")
    cfg.vlm.backend = "stub"
    cfg.embeddings.backend = "stub"
    cfg.robot.backend = "stub"
    cfg.pipeline.max_steps = 2
    cfg.vlm.detector_mode = "complete_at:1"

    bot = PragmaBot(cfg)
    calls = {"n": 0}

    def fake_obs():
        calls["n"] += 1
        return np.full((100, 120, 3), 7, dtype=np.uint8)

    bot.robot.set_observation_source(fake_obs)
    result = bot.run_task("touch the test pattern")
    assert result["success"] is True
    # describe + (before + after) per step + final summary call uses no image.
    assert calls["n"] >= 3
