"""Phase 1 Mac smoke tests — STM, four VLM modules, full pipeline loop."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from omegaconf import OmegaConf

from pragmabot.memory.stm import ShortTermMemory
from pragmabot.pipeline import PragmaBot
from pragmabot.planning import (
    VLMExperienceSummarizer,
    VLMSceneDescriber,
    VLMSuccessDetector,
    VLMTaskPlanner,
)
from pragmabot.robot.stub_robot import StubRobot
from pragmabot.simple_config import load_config
from pragmabot.vlm.stub_vlm import StubVLM


REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "pragmabot" / "config" / "config.yaml"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stub_cfg(tmp_path: Path, **overrides):
    cfg = load_config(CONFIG_PATH)
    cfg.memory.ltm_path = str(tmp_path / "ltm.csv")
    cfg.memory.embeddings_path = str(tmp_path / "ltm_embeddings.npy")
    cfg.vlm.backend = "stub"
    cfg.embeddings.backend = "stub"
    cfg.embeddings.dim = 32
    cfg.robot.backend = "stub"
    for key, value in overrides.items():
        OmegaConf.update(cfg, key, value, merge=True)
    return cfg


def _black_image(h: int = 480, w: int = 640) -> np.ndarray:
    return np.zeros((h, w, 3), dtype=np.uint8)


# ---------------------------------------------------------------------------
# STM
# ---------------------------------------------------------------------------


def test_stm_append_and_format():
    stm = ShortTermMemory()
    stm.append(
        {"skill": "pick", "parameters": {"object": "apple"}},
        {"action_success": False, "task_complete": False, "scene_change": "Apple unmoved."},
    )
    stm.append(
        {"skill": "push", "parameters": {"object": "can", "direction": "right"}},
        {"action_success": True, "task_complete": True, "scene_change": "Can moved 10cm right."},
    )
    text = stm.to_text()
    assert len(stm) == 2
    assert "Step 1: Action: pick(apple). Result: FAILED." in text
    assert "Step 2: Action: push(can, right). Result: SUCCESS." in text
    assert "Apple unmoved." in text
    assert "Can moved 10cm right." in text


def test_stm_reset():
    stm = ShortTermMemory()
    stm.append({"skill": "pick", "parameters": {"object": "x"}}, {"action_success": True})
    assert not stm.is_empty()
    stm.reset()
    assert stm.is_empty()
    assert len(stm) == 0
    assert stm.to_text() == ""


# ---------------------------------------------------------------------------
# Scene describer
# ---------------------------------------------------------------------------


def test_scene_describer_stub(tmp_path):
    cfg = _stub_cfg(tmp_path)
    sd = VLMSceneDescriber(StubVLM(), cfg)
    desc = sd.describe(_black_image(), instruction="pick up the apple")
    assert isinstance(desc, str) and len(desc) > 0


# ---------------------------------------------------------------------------
# Task planner
# ---------------------------------------------------------------------------


def test_task_planner_empty_stm(tmp_path):
    cfg = _stub_cfg(tmp_path)
    planner = VLMTaskPlanner(StubVLM(), cfg)
    action = planner.plan(
        instruction="pick up the apple",
        image=_black_image(),
        stm=ShortTermMemory(),
        ltm_entries=[],
        available_skills=cfg.pipeline.available_skills,
    )
    assert set(action.keys()) >= {"skill", "parameters", "reasoning"}
    assert action["skill"] in list(cfg.pipeline.available_skills)
    assert isinstance(action["parameters"], dict)
    assert isinstance(action["reasoning"], str)


def test_task_planner_with_stm(tmp_path):
    cfg = _stub_cfg(tmp_path)
    vlm = StubVLM()
    planner = VLMTaskPlanner(vlm, cfg)
    stm = ShortTermMemory()
    stm.append(
        {"skill": "pick", "parameters": {"object": "apple"}},
        {
            "action_success": False,
            "task_complete": False,
            "scene_change": "Gripper missed the apple.",
        },
    )
    action = planner.plan(
        instruction="pick up the apple",
        image=_black_image(),
        stm=stm,
        ltm_entries=[],
        available_skills=cfg.pipeline.available_skills,
    )
    assert isinstance(action["reasoning"], str) and len(action["reasoning"]) > 0
    # Reflection instruction must have been injected into the prompt the VLM saw.
    last_prompt = vlm.received_prompts[-1]
    assert "previous action failed" in last_prompt.lower()


def test_task_planner_with_ltm(tmp_path):
    cfg = _stub_cfg(tmp_path)
    vlm = StubVLM()
    planner = VLMTaskPlanner(vlm, cfg)
    ltm_entries = [
        {
            "key": "Instruction: pick the apple\nScene: apple is on table",
            "experience": "Pushed the salt container away first, then picked the apple.",
            "similarity": 0.87,
        }
    ]
    planner.plan(
        instruction="pick up the apple",
        image=_black_image(),
        stm=ShortTermMemory(),
        ltm_entries=ltm_entries,
        available_skills=cfg.pipeline.available_skills,
    )
    last_prompt = vlm.received_prompts[-1]
    assert "past relevant experiences" in last_prompt.lower() or "past experiences" in last_prompt.lower()
    assert "salt container" in last_prompt.lower()


# ---------------------------------------------------------------------------
# Success detector
# ---------------------------------------------------------------------------


def test_success_detector_returns_dict(tmp_path):
    cfg = _stub_cfg(tmp_path)
    det = VLMSuccessDetector(StubVLM(), cfg)
    result = det.evaluate(
        instruction="pick the apple",
        action={"skill": "pick", "parameters": {"object": "apple"}},
        before_image=_black_image(),
        after_image=_black_image(),
    )
    assert set(result.keys()) >= {"action_success", "task_complete", "scene_change", "reasoning"}


def test_success_detector_types(tmp_path):
    cfg = _stub_cfg(tmp_path)
    det = VLMSuccessDetector(StubVLM(), cfg)
    result = det.evaluate(
        instruction="pick the apple",
        action={"skill": "pick", "parameters": {"object": "apple"}},
        before_image=_black_image(),
        after_image=_black_image(),
    )
    assert isinstance(result["action_success"], bool)
    assert isinstance(result["task_complete"], bool)
    assert isinstance(result["scene_change"], str)


# ---------------------------------------------------------------------------
# Experience summarizer
# ---------------------------------------------------------------------------


def test_exp_summarizer_returns_str(tmp_path):
    cfg = _stub_cfg(tmp_path)
    summ = VLMExperienceSummarizer(StubVLM(), cfg)
    stm = ShortTermMemory()
    stm.append(
        {"skill": "pick", "parameters": {"object": "apple"}},
        {"action_success": True, "task_complete": True, "scene_change": "Apple lifted."},
    )
    text = summ.summarize(
        instruction="pick the apple",
        scene_description="The apple is on a table.",
        stm=stm,
    )
    assert isinstance(text, str) and len(text) > 0


# ---------------------------------------------------------------------------
# Stub robot
# ---------------------------------------------------------------------------


def test_stub_robot_logs_calls(tmp_path):
    cfg = _stub_cfg(tmp_path)
    robot = StubRobot(cfg)
    assert robot.is_connected() is True
    robot.execute_pick("apple")
    robot.execute_place("apple", location="plate")
    robot.execute_push("can", direction="right")
    skills = [entry["skill"] for entry in robot.execution_log]
    assert skills == ["pick", "place", "push"]
    assert robot.execution_log[0]["parameters"]["object"] == "apple"
    assert robot.execution_log[1]["parameters"]["location"] == "plate"
    assert robot.execution_log[2]["parameters"]["direction"] == "right"
    obs = robot.get_observation()
    assert obs.shape == (480, 640, 3) and obs.dtype == np.uint8


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------


def test_pipeline_full_loop_success(tmp_path):
    cfg = _stub_cfg(tmp_path)
    cfg.pipeline.max_steps = 5
    cfg.vlm.detector_mode = "complete_at:2"
    bot = PragmaBot(cfg)
    assert len(bot.memory) == 0
    result = bot.run_task("put the apple on the plate")
    assert result["success"] is True
    assert result["steps"] == 2
    assert isinstance(result["experience"], str) and len(result["experience"]) > 0
    assert len(bot.memory) == 1


def test_pipeline_max_steps(tmp_path):
    cfg = _stub_cfg(tmp_path)
    cfg.pipeline.max_steps = 3
    cfg.vlm.detector_mode = "never_complete"
    bot = PragmaBot(cfg)
    result = bot.run_task("move the impossible object")
    assert result["success"] is False
    assert result["steps"] == cfg.pipeline.max_steps
    assert result["experience"] == ""
    assert len(bot.memory) == 0


def test_pipeline_ltm_grows(tmp_path):
    cfg = _stub_cfg(tmp_path)
    cfg.pipeline.max_steps = 3
    cfg.vlm.detector_mode = "always_complete"
    bot = PragmaBot(cfg)

    r1 = bot.run_task("put the apple on the plate")
    assert r1["success"] is True
    assert len(bot.memory) == 1

    r2 = bot.run_task("move the can to the left")
    assert r2["success"] is True
    assert len(bot.memory) == 2


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
