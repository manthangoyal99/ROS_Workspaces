"""Phase 6 Ubuntu integration tests for the evaluation harness."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

try:
    import rospy  # type: ignore  # noqa: F401

    ROS_AVAILABLE = True
except ImportError:
    ROS_AVAILABLE = False

pytestmark = [
    pytest.mark.skipif(not ROS_AVAILABLE, reason="ROS not available"),
    pytest.mark.integration,
]


REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "pragmabot" / "config" / "config.yaml"


@pytest.fixture
def cfg(tmp_path):
    """Per-test config — all stub backends so we exercise the eval harness only."""
    from omegaconf import OmegaConf

    from pragmabot.simple_config import load_config

    base = load_config(CONFIG_PATH)
    overrides = OmegaConf.create({
        "robot": {"backend": "stub"},
        "perception": {"backend": "stub"},
        "vlm": {"backend": "stub", "detector_mode": "always_complete"},
        "embeddings": {"backend": "stub"},
        "memory": {
            "ltm_path": str(tmp_path / "ltm.csv"),
            "embeddings_path": str(tmp_path / "ltm_embeddings.npy"),
        },
        "logging": {"log_dir": str(tmp_path / "episode_logs")},
        "pipeline": {"max_steps": 1},
    })
    return OmegaConf.merge(base, overrides)


def test_evaluator_runs_real_pipeline(cfg, tmp_path):
    from pragmabot.eval import EvaluationConfig, Evaluator, TrialRunner, get_task
    from pragmabot.eval.conditions import ConditionManager
    from pragmabot.pipeline import PragmaBot

    bot = PragmaBot(cfg)
    runner = TrialRunner(bot, cfg, ConditionManager())
    task = get_task("apple_on_plate_container", table="table_2")
    eval_cfg = EvaluationConfig(
        conditions=["pragmabot"],
        tasks=[task],
        n_trials_override=2,
        output_dir=str(tmp_path / "results"),
        resume=False,
    )
    Evaluator(eval_cfg, runner).run()
    trial_dir = tmp_path / "results" / "trials"
    assert any(trial_dir.glob("*.json"))


def test_table2_csv_format(cfg, tmp_path):
    from pragmabot.eval import (EvaluationConfig, Evaluator, ResultAggregator,
                                TrialRunner, get_task)
    from pragmabot.eval.conditions import ConditionManager
    from pragmabot.pipeline import PragmaBot

    bot = PragmaBot(cfg)
    runner = TrialRunner(bot, cfg, ConditionManager())
    task = get_task("apple_on_plate_container", table="table_2")
    eval_cfg = EvaluationConfig(
        conditions=["cap_v", "pragmabot"],
        tasks=[task],
        n_trials_override=1,
        output_dir=str(tmp_path / "results"),
        resume=False,
    )
    Evaluator(eval_cfg, runner).run()
    agg = ResultAggregator(str(tmp_path / "results"))
    csv_path = agg.generate_table_2_csv()
    with csv_path.open() as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    assert len(rows) == 5  # 4 tasks + MEAN
    for col in ("task_name", "cap_v_pct", "pragmabot_pct", "delta_pct"):
        assert col in reader.fieldnames


def test_timing_fields_populated(cfg, tmp_path):
    from pragmabot.eval import TrialConfig, TrialRunner
    from pragmabot.eval.conditions import ConditionManager
    from pragmabot.pipeline import PragmaBot

    bot = PragmaBot(cfg)
    runner = TrialRunner(bot, cfg, ConditionManager())
    trial = TrialConfig(
        task_name="apple", instruction="pick the apple", trial_id=0,
        condition="pragmabot", use_stm=True, use_ltm=True,
    )
    result = runner.run(trial)
    keys = ("mean_planning_time_sec", "mean_execution_time_sec",
            "mean_detection_time_sec", "mean_perception_time_sec")
    for k in keys:
        assert k in result.per_step_timings
    # At least one timing should be non-zero from the real pipeline.
    assert any(v > 0 for v in result.per_step_timings.values())
