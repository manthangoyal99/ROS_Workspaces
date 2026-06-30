"""Phase 4 Mac tests — Franka import safety, grasp synthesis, 3D pipeline path."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from pragmabot.pipeline import PragmaBot
from pragmabot.robot.factory import get_robot
from pragmabot.robot.grasp import (
    BaseGraspSynthesizer,
    GraspCandidate,
    TopDownGraspSynthesizer,
    get_grasp_synthesizer,
)
from pragmabot.robot.stub_robot import StubRobot
from pragmabot.simple_config import load_config


REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "pragmabot" / "config" / "config.yaml"


def _stub_cfg(tmp_path: Path):
    cfg = load_config(CONFIG_PATH)
    cfg.memory.ltm_path = str(tmp_path / "ltm.csv")
    cfg.memory.embeddings_path = str(tmp_path / "ltm_embeddings.npy")
    cfg.vlm.backend = "stub"
    cfg.embeddings.backend = "stub"
    cfg.embeddings.dim = 32
    cfg.robot.backend = "stub"
    cfg.perception.backend = "stub"
    return cfg


# ---------------------------------------------------------------------------
# Module import safety
# ---------------------------------------------------------------------------


def test_franka_robot_import_guard():
    """Importing the module on Mac must succeed; ROS_AVAILABLE must be False."""
    from pragmabot.robot import franka_ros

    assert franka_ros.ROS_AVAILABLE is False
    assert hasattr(franka_ros, "FrankaRobot")


def test_franka_robot_raises_without_ros(tmp_path):
    """Constructing FrankaRobot on Mac must raise a helpful RuntimeError."""
    cfg = _stub_cfg(tmp_path)
    from pragmabot.robot.franka_ros import FrankaRobot

    with pytest.raises(RuntimeError, match=r"ROS"):
        FrankaRobot(cfg)


def test_robot_factory_franka_raises_on_mac(tmp_path):
    """The factory must surface FrankaRobot.__init__'s RuntimeError on Mac."""
    cfg = _stub_cfg(tmp_path)
    cfg.robot.backend = "franka_ros"
    with pytest.raises(RuntimeError, match=r"ROS"):
        get_robot(cfg)


# ---------------------------------------------------------------------------
# Grasp synthesizer
# ---------------------------------------------------------------------------


def test_top_down_grasp_synthesizer(tmp_path):
    cfg = _stub_cfg(tmp_path)
    synth = TopDownGraspSynthesizer(cfg)
    target = np.array([0.4, 0.0, 0.3])
    candidates = synth.synthesize("apple", target_position=target)
    assert len(candidates) == 1
    cand = candidates[0]
    assert isinstance(cand, GraspCandidate)
    assert cand.confidence == 1.0
    # Top-down approach vector should point straight down.
    assert np.allclose(cand.approach_vector, [0.0, 0.0, -1.0])
    # Grasp position is AT the object, with a small sink-into-object depth
    # subtracted. The approach height is applied by execute_pick separately
    # when it builds the pre-grasp pose.
    expected_z = target[2] - cfg.robot.grasp.grasp_height_offset
    assert np.isclose(cand.pose_matrix[2, 3], expected_z, atol=1e-6)
    assert np.allclose(cand.position[:2], target[:2])


def test_grasp_pose_matrix_shape(tmp_path):
    cfg = _stub_cfg(tmp_path)
    synth = TopDownGraspSynthesizer(cfg)
    cand = synth.synthesize("apple", target_position=np.array([0.4, 0.0, 0.3]))[0]
    assert cand.pose_matrix.shape == (4, 4)
    # Last row of homogeneous SE(3): [0, 0, 0, 1].
    assert np.allclose(cand.pose_matrix[3], [0.0, 0.0, 0.0, 1.0])


def test_grasp_factory_top_down(tmp_path):
    cfg = _stub_cfg(tmp_path)
    synth = get_grasp_synthesizer(cfg)
    assert isinstance(synth, TopDownGraspSynthesizer)
    assert synth.backend_name == "top_down"
    assert isinstance(synth, BaseGraspSynthesizer)


def test_grasp_factory_anygrasp_not_implemented(tmp_path):
    cfg = _stub_cfg(tmp_path)
    cfg.robot.grasp.backend = "anygrasp"
    with pytest.raises(NotImplementedError, match="AnyGrasp"):
        get_grasp_synthesizer(cfg)


def test_cartesian_path_empty(tmp_path):
    """No point cloud is OK as long as target_position is provided."""
    cfg = _stub_cfg(tmp_path)
    synth = TopDownGraspSynthesizer(cfg)
    cand = synth.synthesize(
        "apple",
        point_cloud=None,
        target_position=np.array([0.4, 0.0, 0.3]),
    )[0]
    assert cand.confidence == 1.0
    assert cand.pose_matrix.shape == (4, 4)


# ---------------------------------------------------------------------------
# Stub robot — Phase 3 signatures still work; positions land in execution_log
# ---------------------------------------------------------------------------


def test_stub_robot_pick_logs_position():
    robot = StubRobot()
    target = np.array([0.4, 0.0, 0.3])
    robot.execute_pick("apple", target_position_3d=target)
    assert len(robot.execution_log) == 1
    entry = robot.execution_log[0]
    assert entry["skill"] == "pick"
    pos = entry["parameters"]["target_position_3d"]
    assert pos is not None
    assert np.allclose(pos, target.tolist())


def test_stub_robot_push_direction_logged():
    robot = StubRobot()
    robot.execute_push("can", direction="left")
    entry = robot.execution_log[0]
    assert entry["skill"] == "push"
    assert entry["parameters"]["direction"] == "left"


def test_robot_factory_stub(tmp_path):
    cfg = _stub_cfg(tmp_path)
    robot = get_robot(cfg)
    assert isinstance(robot, StubRobot)
    assert robot.backend_name == "stub"


# ---------------------------------------------------------------------------
# Pipeline end-to-end: 3D positions flow from perception to robot
# ---------------------------------------------------------------------------


def test_pipeline_with_3d_positions(tmp_path):
    cfg = _stub_cfg(tmp_path)
    cfg.pipeline.max_steps = 1
    cfg.vlm.detector_mode = "always_complete"
    bot = PragmaBot(cfg)
    bot.run_task("pick up the apple")
    assert isinstance(bot.robot, StubRobot)
    assert len(bot.robot.execution_log) >= 1
    pick = next(e for e in bot.robot.execution_log if e["skill"] == "pick")
    # StubPerception synthesizes (0.3 + i*0.1, 0.0, 0.5) for the i-th query;
    # "apple" is the first detected object.
    pos = pick["parameters"]["target_position_3d"]
    assert pos is not None
    assert np.allclose(pos, [0.3, 0.0, 0.5], atol=1e-6)


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
