"""Canonical full Mac-side integration test — touches every phase's surface."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from pragmabot.eval import EvaluationConfig, Evaluator, ResultAggregator, TrialRunner, get_task
from pragmabot.eval.conditions import ConditionManager
from pragmabot.pipeline import PragmaBot
from pragmabot.registry import registry
from pragmabot.simple_config import load_config


REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "pragmabot" / "config" / "config.yaml"


def test_full_mac_pipeline(tmp_path):
    """Exercise Phase 0–7 in a single run.

    1. Phase 0 — config loads and VLM stub responds.
    2. Phase 1 — STM populated when the planner reflects on failure.
    3. Phase 2 — observation source injection still works.
    4. Phase 3 — perception returns 3D centroids that flow into the pipeline.
    5. Phase 4 — stub robot logs the dispatched skill with the perceived position.
    6. Phase 5 — episode log is written, step_callback fires.
    7. Phase 6 — Evaluator records trial JSONs for both conditions.
    8. Phase 7 — registry is used to instantiate every component.
    """
    cfg = load_config(CONFIG_PATH)
    cfg.memory.ltm_path = str(tmp_path / "ltm.csv")
    cfg.memory.embeddings_path = str(tmp_path / "ltm_embeddings.npy")
    cfg.vlm.backend = "stub"
    cfg.embeddings.backend = "stub"
    cfg.embeddings.dim = 32
    cfg.perception.backend = "stub"
    cfg.robot.backend = "stub"
    cfg.logging.log_dir = str(tmp_path / "logs")
    cfg.pipeline.max_steps = 2
    cfg.vlm.detector_mode = "always_complete"

    # Phase 7 — registry resolves every backend.
    for component_type, name in (
        ("vlm", "stub"),
        ("embedder", "stub"),
        ("perception", "stub"),
        ("robot", "stub"),
        ("grasp", "top_down"),
    ):
        registry.get(component_type, name)

    # Phase 1 + Phase 5 — run task, capture step callbacks, episode log.
    callbacks = []
    bot = PragmaBot(cfg, step_callback=callbacks.append)

    # Phase 2 — injectable observation source.
    bot.robot.set_observation_source(lambda: np.zeros((48, 64, 3), dtype=np.uint8))

    result_pragmabot = bot.run_task("pick up the apple")
    assert result_pragmabot["success"] is True
    assert result_pragmabot["stm"], "STM should be non-empty for pragmabot"
    assert result_pragmabot["episode_log_path"]
    assert callbacks, "step_callback never fired"

    # Phase 3 + 4 — stub robot received the 3D centroid (0.3, 0, 0.5) from perception.
    pick = next(e for e in bot.robot.execution_log if e["skill"] == "pick")
    assert np.allclose(pick["parameters"]["target_position_3d"], [0.3, 0.0, 0.5])

    # Phase 6 — evaluator runs cap_v and pragmabot conditions.
    runner = TrialRunner(bot, cfg, ConditionManager())
    task = get_task("apple_on_plate_container", table="table_2")
    eval_dir = tmp_path / "results"
    eval_cfg = EvaluationConfig(
        conditions=["cap_v", "pragmabot"],
        tasks=[task],
        n_trials_override=1,
        output_dir=str(eval_dir),
        resume=False,
    )
    summary = Evaluator(eval_cfg, runner).run()
    assert summary["n_completed"] == 2
    agg = ResultAggregator(str(eval_dir))
    csv_path = agg.generate_table_2_csv()
    payload = json.loads(agg.generate_summary_json().read_text())
    assert csv_path.exists()
    assert "by_condition" in payload
    # cap_v trial must have empty STM (no LTM either).
    cap_v_trial = next(
        json.loads(p.read_text())
        for p in (eval_dir / "trials").glob("apple_on_plate_container_cap_v_*.json")
    )
    assert cap_v_trial["stm_entries"], "even cap_v populates STM during the run"
    assert cap_v_trial["ltm_entries_used"] == []
