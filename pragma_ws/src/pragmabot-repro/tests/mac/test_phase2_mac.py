"""Phase 2 Mac-safe tests — no ROS imports, only static checks + injection logic."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from pragmabot.robot.stub_robot import StubRobot
from pragmabot.simple_config import load_config


REPO_ROOT = Path(__file__).resolve().parents[2]
PKG_ROOT = REPO_ROOT / "pragmabot"
CONFIG_PATH = PKG_ROOT / "config" / "config.yaml"

ROS_GUARD_SNIPPETS = ("import rospy", "ROS_AVAILABLE")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# ROS guard presence in every ROS-touching file
# ---------------------------------------------------------------------------


def test_ros_guard_in_scene_observer():
    text = _read(PKG_ROOT / "src" / "pragmabot" / "ros" / "scene_observer.py")
    for snippet in ROS_GUARD_SNIPPETS:
        assert snippet in text, f"scene_observer.py missing ROS guard snippet: {snippet!r}"
    assert "except ImportError" in text


def test_ros_guard_in_image_utils():
    text = _read(PKG_ROOT / "src" / "pragmabot" / "ros" / "image_utils.py")
    for snippet in ROS_GUARD_SNIPPETS:
        assert snippet in text
    assert "except ImportError" in text


@pytest.mark.parametrize(
    "node_filename",
    ["pragmabot_node.py", "memory_manager_node.py", "image_republisher_node.py"],
)
def test_ros_guard_in_nodes(node_filename: str):
    text = _read(PKG_ROOT / "nodes" / node_filename)
    for snippet in ROS_GUARD_SNIPPETS:
        assert snippet in text, f"{node_filename} missing ROS guard snippet: {snippet!r}"
    assert "except ImportError" in text


# ---------------------------------------------------------------------------
# Observation source injection works on the stub robot
# ---------------------------------------------------------------------------


def test_observation_source_injection():
    robot = StubRobot()
    called = {"n": 0}

    def fake() -> np.ndarray:
        called["n"] += 1
        return np.full((10, 20, 3), 42, dtype=np.uint8)

    # Native observation is a black 480x640 image.
    native = robot.get_observation()
    assert native.shape == (480, 640, 3)
    assert native.sum() == 0
    assert robot.has_observation_source() is False

    robot.set_observation_source(fake)
    assert robot.has_observation_source() is True

    obs = robot.get_observation()
    assert obs.shape == (10, 20, 3)
    assert (obs == 42).all()
    assert called["n"] == 1

    # Clearing restores the native source.
    robot.set_observation_source(None)
    again = robot.get_observation()
    assert again.shape == (480, 640, 3)
    assert again.sum() == 0


def test_set_observation_source_rejects_non_callable():
    robot = StubRobot()
    with pytest.raises(TypeError):
        robot.set_observation_source(42)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Config ROS section
# ---------------------------------------------------------------------------


def test_config_ros_section_keys():
    cfg = load_config(CONFIG_PATH)
    assert "ros" in cfg
    required = ("rgb_topic", "depth_topic", "image_timeout_sec", "rosbag_replay")
    for key in required:
        assert key in cfg.ros, f"config.ros missing {key!r}"
    assert isinstance(cfg.ros.image_timeout_sec, (int, float))
    assert isinstance(bool(cfg.ros.rosbag_replay), bool)


# ---------------------------------------------------------------------------
# Catkin / launch artifacts exist
# ---------------------------------------------------------------------------


def test_package_xml_exists_and_parses():
    import xml.etree.ElementTree as ET

    pkg = PKG_ROOT / "package.xml"
    assert pkg.exists()
    tree = ET.parse(pkg)
    root = tree.getroot()
    assert root.tag == "package"
    name = root.find("name")
    assert name is not None and name.text == "pragmabot"


@pytest.mark.parametrize(
    "launch_name",
    [
        "launch_pragmabot.launch",
        "replay_rosbag.launch",
        "manage_memory.launch",
        "record_rosbag.launch",
    ],
)
def test_launch_files_exist(launch_name: str):
    import xml.etree.ElementTree as ET

    path = PKG_ROOT / "launch" / launch_name
    assert path.exists()
    ET.parse(path)  # valid XML
    # Must use $(find pragmabot) rather than absolute paths for any paths.
    text = path.read_text(encoding="utf-8")
    assert "$(find pragmabot)" in text or "$(arg" in text or "$(env" in text or "rosbag" in text


# ---------------------------------------------------------------------------
# Pipeline asserts stub robot in rosbag-replay mode
# ---------------------------------------------------------------------------


def test_pipeline_rejects_non_stub_robot_in_replay_mode(tmp_path):
    from pragmabot.pipeline import PragmaBot

    cfg = load_config(CONFIG_PATH)
    cfg.memory.ltm_path = str(tmp_path / "ltm.csv")
    cfg.memory.embeddings_path = str(tmp_path / "ltm_embeddings.npy")
    cfg.ros.rosbag_replay = True
    cfg.robot.backend = "stub"
    # Stub passes.
    PragmaBot(cfg)

    # Now flip backend to something else and verify the constructor raises.
    class FakeRobot(StubRobot):
        @property
        def backend_name(self) -> str:
            return "franka_ros"

    cfg.vlm.backend = "stub"
    cfg.embeddings.backend = "stub"
    with pytest.raises(ValueError, match="rosbag_replay"):
        PragmaBot(cfg, robot=FakeRobot())


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
