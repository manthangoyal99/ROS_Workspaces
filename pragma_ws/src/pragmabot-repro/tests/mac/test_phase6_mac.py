"""Phase 6 Mac tests — task suite, conditions, trial runner, aggregator, report."""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

from pragmabot.eval import (
    CONDITIONS,
    ConditionManager,
    EvaluationConfig,
    Evaluator,
    ReportGenerator,
    ResultAggregator,
    TABLE_2_TASKS,
    TABLE_3_TASKS,
    TaskDefinition,
    TrialConfig,
    TrialResult,
    TrialRunner,
    get_table_tasks,
    get_task,
)
from pragmabot.eval.trial_runner import save_trial_result
from pragmabot.pipeline import PragmaBot
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
    cfg.logging.log_dir = str(tmp_path / "episode_logs")
    cfg.pipeline.max_steps = 2
    cfg.vlm.detector_mode = "always_complete"
    return cfg


# ---------------------------------------------------------------------------
# Task suite
# ---------------------------------------------------------------------------


def test_task_suite_table2_count():
    assert len(TABLE_2_TASKS) == 4


def test_task_suite_table3_count():
    assert len(TABLE_3_TASKS) == 12


def test_task_suite_get_task():
    task = get_task("apple_on_plate_container", table="table_2")
    assert isinstance(task, TaskDefinition)
    assert task.paper_table == "table_2"
    assert "apple" in task.objects_required


def test_task_suite_get_table():
    table2 = get_table_tasks("table_2")
    assert len(table2) == 4
    table3 = get_table_tasks("table_3")
    assert len(table3) == 12


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


def test_trial_config_fields():
    cfg = TrialConfig(
        task_name="t",
        instruction="i",
        trial_id=0,
        condition="pragmabot",
        use_stm=True,
        use_ltm=True,
    )
    for attr in ("task_name", "instruction", "trial_id", "condition",
                 "use_stm", "use_ltm", "max_steps", "timeout_sec",
                 "scene_reset_fn", "paper_table"):
        assert hasattr(cfg, attr)


def test_trial_result_fields(tmp_path):
    cfg = _stub_cfg(tmp_path)
    bot = PragmaBot(cfg)
    runner = TrialRunner(bot, cfg)
    trial = TrialConfig(
        task_name="apple", instruction="pick the apple", trial_id=0,
        condition="pragmabot", use_stm=True, use_ltm=True,
    )
    result = runner.run(trial)
    assert isinstance(result, TrialResult)
    for attr in ("success", "steps", "duration_sec", "episode_log_path",
                 "failure_reason", "stm_entries", "ltm_entries_used",
                 "per_step_timings", "error", "timestamp"):
        assert hasattr(result, attr)


# ---------------------------------------------------------------------------
# TrialRunner
# ---------------------------------------------------------------------------


def test_trial_runner_success(tmp_path):
    cfg = _stub_cfg(tmp_path)
    cfg.vlm.detector_mode = "complete_at:1"
    bot = PragmaBot(cfg)
    runner = TrialRunner(bot, cfg)
    trial = TrialConfig(
        task_name="apple", instruction="pick the apple", trial_id=0,
        condition="pragmabot", use_stm=True, use_ltm=True, max_steps=3,
    )
    result = runner.run(trial)
    assert result.success is True
    assert result.steps == 1
    assert result.error is None


def test_trial_runner_failure(tmp_path):
    cfg = _stub_cfg(tmp_path)
    cfg.vlm.detector_mode = "never_complete"
    bot = PragmaBot(cfg)
    runner = TrialRunner(bot, cfg)
    trial = TrialConfig(
        task_name="apple", instruction="pick the apple", trial_id=0,
        condition="pragmabot", use_stm=True, use_ltm=True, max_steps=3,
    )
    result = runner.run(trial)
    assert result.success is False
    assert result.steps == 3
    assert result.error is None  # not a crash, just unsuccessful


def test_trial_runner_crash_recovery(tmp_path):
    cfg = _stub_cfg(tmp_path)
    bot = PragmaBot(cfg)
    runner = TrialRunner(bot, cfg)

    # Force the pipeline to raise on run_task.
    def boom(*args, **kwargs):
        raise RuntimeError("simulated pipeline crash")

    bot.run_task = boom  # type: ignore[assignment]
    trial = TrialConfig(
        task_name="apple", instruction="pick the apple", trial_id=0,
        condition="pragmabot", use_stm=True, use_ltm=True,
    )
    result = runner.run(trial)
    assert result.success is False
    assert result.error is not None
    assert "simulated pipeline crash" in result.error


# ---------------------------------------------------------------------------
# Conditions
# ---------------------------------------------------------------------------


def test_condition_cap_v(tmp_path):
    cfg = _stub_cfg(tmp_path)
    bot = PragmaBot(cfg)
    manager = ConditionManager()
    assert bot.activate_stm is True
    assert bot.activate_ltm is True
    with manager.apply("cap_v", bot):
        assert bot.activate_stm is False
        assert bot.activate_ltm is False


def test_condition_pragmabot_full(tmp_path):
    cfg = _stub_cfg(tmp_path)
    bot = PragmaBot(cfg)
    manager = ConditionManager()
    with manager.apply("pragmabot", bot):
        assert bot.activate_stm is True
        assert bot.activate_ltm is True


def test_condition_manager_restores(tmp_path):
    cfg = _stub_cfg(tmp_path)
    bot = PragmaBot(cfg)
    manager = ConditionManager()
    prev_stm, prev_ltm = bot.activate_stm, bot.activate_ltm
    try:
        with manager.apply("cap_v", bot):
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert bot.activate_stm == prev_stm
    assert bot.activate_ltm == prev_ltm


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------


def _write_fake_trial(out_dir: Path, task_name: str, condition: str, trial_id: int,
                     success: bool, steps: int = 1, error: str = None) -> None:
    (out_dir / "trials").mkdir(parents=True, exist_ok=True)
    payload = {
        "trial_id": trial_id,
        "task_name": task_name,
        "condition": condition,
        "instruction": "x",
        "success": success,
        "steps": steps,
        "duration_sec": 0.1,
        "failure_reason": None if success else "did not complete",
        "error": error,
        "stm_entries": [],
        "ltm_entries_used": [],
        "per_step_timings": {
            "mean_planning_time_sec": 0.01,
            "mean_execution_time_sec": 0.02,
            "mean_detection_time_sec": 0.03,
            "mean_perception_time_sec": 0.0,
        },
        "episode_log_path": "",
        "timestamp": "2026-06-03T00:00:00",
    }
    fname = f"{task_name}_{condition}_trial{trial_id:02d}.json"
    (out_dir / "trials" / fname).write_text(json.dumps(payload), encoding="utf-8")


def test_aggregator_success_rate(tmp_path):
    _write_fake_trial(tmp_path, "apple_on_plate_container", "pragmabot", 0, True)
    _write_fake_trial(tmp_path, "apple_on_plate_container", "pragmabot", 1, True)
    _write_fake_trial(tmp_path, "apple_on_plate_container", "pragmabot", 2, False)
    agg = ResultAggregator(str(tmp_path))
    stats = agg.compute_task_stats("apple_on_plate_container", "pragmabot")
    assert stats["n_trials"] == 3
    assert stats["n_success"] == 2
    assert stats["success_rate"] == pytest.approx(2 / 3, abs=1e-6)


def test_aggregator_delta(tmp_path):
    _write_fake_trial(tmp_path, "apple_on_plate_container", "cap_v", 0, False)
    _write_fake_trial(tmp_path, "apple_on_plate_container", "cap_v", 1, True)
    _write_fake_trial(tmp_path, "apple_on_plate_container", "pragmabot", 0, True)
    _write_fake_trial(tmp_path, "apple_on_plate_container", "pragmabot", 1, True)
    agg = ResultAggregator(str(tmp_path))
    delta = agg.compute_delta("apple_on_plate_container", "cap_v", "pragmabot")
    assert delta["delta_success_rate"] == pytest.approx(0.5, abs=1e-6)
    assert delta["delta_success_rate_pct"] == pytest.approx(50.0, abs=1e-3)


def test_aggregator_table2_csv(tmp_path):
    _write_fake_trial(tmp_path, "apple_on_plate_container", "cap_v", 0, False)
    _write_fake_trial(tmp_path, "apple_on_plate_container", "pragmabot", 0, True)
    agg = ResultAggregator(str(tmp_path))
    out = agg.generate_table_2_csv()
    assert out.exists()
    with out.open() as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        rows = list(reader)
    assert "task_name" in headers
    assert "cap_v_pct" in headers
    assert "pragmabot_pct" in headers
    assert "delta_pct" in headers
    # 4 task rows + MEAN.
    assert len(rows) == 5


def test_aggregator_summary_json(tmp_path):
    _write_fake_trial(tmp_path, "apple_on_plate_container", "cap_v", 0, False)
    _write_fake_trial(tmp_path, "apple_on_plate_container", "pragmabot", 0, True)
    agg = ResultAggregator(str(tmp_path))
    out = agg.generate_summary_json()
    payload = json.loads(out.read_text())
    assert "vs_paper" in payload
    assert "by_condition" in payload


# ---------------------------------------------------------------------------
# Evaluator + Resume
# ---------------------------------------------------------------------------


def test_evaluator_resume(tmp_path):
    cfg = _stub_cfg(tmp_path)
    bot = PragmaBot(cfg)
    runner = TrialRunner(bot, cfg)
    task = get_task("apple_on_plate_container", table="table_2")
    eval_cfg = EvaluationConfig(
        conditions=["pragmabot"],
        tasks=[task],
        n_trials_override=2,
        output_dir=str(tmp_path / "results"),
        resume=True,
    )
    evaluator = Evaluator(eval_cfg, runner)
    s1 = evaluator.run()
    s2 = evaluator.run()  # resume — should skip everything
    assert s1["n_completed"] == 2
    assert s2["n_completed"] == 0
    assert s2["n_skipped"] == 2


# ---------------------------------------------------------------------------
# Report generator
# ---------------------------------------------------------------------------


def test_report_generator_creates_file(tmp_path):
    _write_fake_trial(tmp_path, "apple_on_plate_container", "cap_v", 0, False)
    _write_fake_trial(tmp_path, "apple_on_plate_container", "pragmabot", 0, True)
    agg = ResultAggregator(str(tmp_path))
    agg.generate_table_2_csv()
    agg.generate_summary_json()
    out = ReportGenerator(agg).generate(str(tmp_path / "report.md"))
    text = out.read_text(encoding="utf-8")
    assert "PragmaBot evaluation report" in text
    assert "Table II reproduction" in text


# ---------------------------------------------------------------------------
# CLI smoke
# ---------------------------------------------------------------------------


def test_run_evaluation_script_stub(tmp_path):
    out_dir = tmp_path / "cli_out"
    cmd = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "run_evaluation.py"),
        "--task", "apple_on_plate_container",
        "--conditions", "pragmabot",
        "--n_trials", "1",
        "--output_dir", str(out_dir),
        "--stub",
    ]
    completed = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    assert completed.returncode == 0, completed.stderr
    csv_path = out_dir / "aggregate" / "table_2_results.csv"
    assert csv_path.exists()


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
