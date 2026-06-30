"""Phase 5 Mac tests — episode logging, step callbacks, error handling, timings."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pytest

from pragmabot.errors import (
    ExecutionError,
    PerceptionError,
    PlanningError,
    PragmaBotError,
    PragmaBotMemoryError,
    VLMError,
)
from pragmabot.logging.episode_logger import EpisodeLogger
from pragmabot.pipeline import PragmaBot
from pragmabot.simple_config import load_config
from pragmabot.vlm.stub_vlm import StubVLM


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
    cfg.logging.log_dir = str(tmp_path / "logs")
    cfg.pipeline.max_steps = 2
    cfg.vlm.detector_mode = "complete_at:1"
    return cfg


# ---------------------------------------------------------------------------
# Error hierarchy
# ---------------------------------------------------------------------------


def test_pragmabot_error_hierarchy():
    for cls in (PlanningError, ExecutionError, PerceptionError,
                PragmaBotMemoryError, VLMError):
        assert issubclass(cls, PragmaBotError)


# ---------------------------------------------------------------------------
# EpisodeLogger
# ---------------------------------------------------------------------------


def test_episode_logger_start_end(tmp_path):
    cfg = _stub_cfg(tmp_path)
    log = EpisodeLogger(tmp_path / "logs")
    eid = log.start_episode("pick up the apple", cfg)
    log.log_step(
        1,
        {"skill": "pick", "parameters": {"object": "apple"}},
        {"action_success": True, "task_complete": False},
        timings={"planning_time_sec": 0.1, "execution_time_sec": 0.2, "detection_time_sec": 0.3},
    )
    log.log_step(
        2,
        {"skill": "place", "parameters": {"object": "apple"}},
        {"action_success": True, "task_complete": True},
        timings={"planning_time_sec": 0.4, "execution_time_sec": 0.5, "detection_time_sec": 0.6},
    )
    path = log.end_episode(
        success=True,
        experience="picked then placed",
        scenario_key="Instruction: pick up the apple\nScene: ...",
        ltm_entries_used=[],
    )
    assert Path(path).exists()
    payload = json.loads(Path(path).read_text())
    assert payload["episode_id"] == eid
    assert payload["steps"] == 2
    assert payload["success"] is True


def test_episode_logger_fields(tmp_path):
    cfg = _stub_cfg(tmp_path)
    log = EpisodeLogger(tmp_path / "logs")
    log.start_episode("t", cfg)
    log.log_step(1, {"skill": "pick"}, {"action_success": True})
    path = log.end_episode(True, "exp", "scenario", [])
    payload = json.loads(Path(path).read_text())
    required = {
        "episode_id", "instruction", "timestamp_start", "timestamp_end",
        "success", "steps", "scenario_key", "ltm_entries_used",
        "stm", "experience_stored", "config_snapshot",
    }
    assert required.issubset(payload.keys())
    step_required = {
        "step", "action", "feedback",
        "planning_time_sec", "execution_time_sec", "detection_time_sec",
    }
    assert step_required.issubset(payload["stm"][0].keys())


def test_episode_logger_load(tmp_path):
    cfg = _stub_cfg(tmp_path)
    log = EpisodeLogger(tmp_path / "logs")
    log.start_episode("hello", cfg)
    log.log_step(1, {"skill": "noop"}, {"action_success": False})
    path = log.end_episode(False, "", "key", [])
    loaded = EpisodeLogger.load_episode(path)
    assert loaded["instruction"] == "hello"
    assert loaded["success"] is False


# ---------------------------------------------------------------------------
# Pipeline callbacks + timings + episode log
# ---------------------------------------------------------------------------


def test_pipeline_step_callback(tmp_path):
    cfg = _stub_cfg(tmp_path)
    received: List[Dict[str, Any]] = []
    bot = PragmaBot(cfg, step_callback=received.append)
    bot.run_task("pick up the apple")
    assert len(received) >= 3
    for payload in received:
        assert "phase" in payload
        assert "step" in payload
        assert "stm_text" in payload
        assert "ltm_count" in payload
        assert "message" in payload


def test_pipeline_timing_in_result(tmp_path):
    cfg = _stub_cfg(tmp_path)
    bot = PragmaBot(cfg)
    result = bot.run_task("pick up the apple")
    assert result["stm"], "expected at least one STM entry"
    timings = result["stm"][0]["feedback"]["_timings"]
    for key in ("planning_time_sec", "execution_time_sec",
                "detection_time_sec", "perception_time_sec"):
        assert key in timings
        assert timings[key] >= 0.0


def test_pipeline_saves_episode_log(tmp_path):
    cfg = _stub_cfg(tmp_path)
    cfg.logging.save_episodes = True
    bot = PragmaBot(cfg)
    result = bot.run_task("pick up the apple")
    assert result["episode_log_path"], "expected episode_log_path in result"
    path = Path(result["episode_log_path"])
    assert path.exists()
    payload = json.loads(path.read_text())
    assert payload["success"] is True
    assert payload["instruction"] == "pick up the apple"


# ---------------------------------------------------------------------------
# Graceful error paths
# ---------------------------------------------------------------------------


class _RaisingVLM(StubVLM):
    """StubVLM that raises on the second `chat_with_image` call."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self._calls = 0

    def chat_with_image(self, messages, images):
        self._calls += 1
        if self._calls == 2:
            raise RuntimeError("simulated VLM crash on second call")
        return super().chat_with_image(messages, images)


def test_pipeline_error_handling_planning(tmp_path):
    cfg = _stub_cfg(tmp_path)
    bot = PragmaBot(cfg, vlm=_RaisingVLM())
    result = bot.run_task("pick up the apple")
    assert result["success"] is False
    assert result["error"], "error message expected on graceful failure"
    # An episode log must have been written even though the task failed.
    assert result["episode_log_path"] and Path(result["episode_log_path"]).exists()


def test_pipeline_error_handling_execution(tmp_path):
    cfg = _stub_cfg(tmp_path)
    bot = PragmaBot(cfg)

    def boom(*args, **kwargs):
        raise RuntimeError("simulated robot crash")

    bot.robot.execute_skill = boom  # type: ignore[assignment]
    result = bot.run_task("pick up the apple")
    assert result["success"] is False
    assert "execution" in (result["error"] or "").lower()
    assert result["episode_log_path"] and Path(result["episode_log_path"]).exists()


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
