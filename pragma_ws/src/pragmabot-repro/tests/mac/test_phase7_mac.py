"""Phase 7 Mac tests — registry, baselines, ablation, reproducibility, viz, docs."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from pragmabot.ablation import AblationConfigBuilder, AblationRunner
from pragmabot.baselines import CaPVBaseline, COMEBaseline, get_baseline
from pragmabot.baselines.base import BaseBaseline
from pragmabot.eval import get_task
from pragmabot.pipeline import PragmaBot
from pragmabot.registry import ComponentRegistry, registry
from pragmabot.simple_config import load_config
from pragmabot.utils.reproducibility import (
    assert_backends_available,
    config_hash,
    get_system_info,
    save_run_metadata,
)
from pragmabot.utils.viz import plot_success_rates, plot_timing_breakdown
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
    cfg.vlm.detector_mode = "always_complete"
    return cfg


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_registry_register_and_get():
    r = ComponentRegistry()

    @r.register("vlm", "fake")
    class Fake:
        pass

    assert r.get("vlm", "fake") is Fake


def test_registry_list_available():
    vlm_names = registry.list_available("vlm")
    assert "stub" in vlm_names
    # ollama / openai are best-effort but at least the stub must be registered
    assert set(vlm_names) >= {"stub"}


def test_registry_unknown_raises():
    with pytest.raises(KeyError, match=r"backend 'nope'"):
        registry.get("vlm", "nope")


def test_registry_instantiate():
    obj = registry.instantiate("vlm", "stub")
    assert obj.backend_name == "stub"


def test_all_factories_use_registry():
    expected = "registry"
    sources = [
        REPO_ROOT / "pragmabot" / "src" / "pragmabot" / "vlm" / "factory.py",
        REPO_ROOT / "pragmabot" / "src" / "pragmabot" / "perception" / "factory.py",
        REPO_ROOT / "pragmabot" / "src" / "pragmabot" / "robot" / "factory.py",
        REPO_ROOT / "pragmabot" / "src" / "pragmabot" / "robot" / "grasp" / "factory.py",
        REPO_ROOT / "pragmabot" / "src" / "pragmabot" / "memory" / "embeddings.py",
    ]
    for path in sources:
        text = path.read_text(encoding="utf-8")
        assert expected in text, f"{path.name} does not reference the registry"


def test_baseline_registry_entries():
    names = registry.list_available("baseline")
    assert set(names) >= {"cap_v", "come"}


# ---------------------------------------------------------------------------
# Ablation
# ---------------------------------------------------------------------------


def test_ablation_config_builder_sweep(tmp_path):
    builder = AblationConfigBuilder(CONFIG_PATH)
    builder.sweep("memory.top_k", [1, 3, 5])
    builder.sweep("vlm.temperature", [0.0, 0.3])
    configs = builder.build()
    assert len(configs) == 6
    assert len(builder) == 6


def test_ablation_config_builder_names(tmp_path):
    builder = AblationConfigBuilder(CONFIG_PATH)
    builder.sweep("memory.top_k", [1, 3]).sweep("vlm.temperature", [0.0])
    names = [n for n, _ in builder.build()]
    assert "memory_top_k=1__vlm_temperature=0" in names[0]
    assert all("memory_top_k" in n and "vlm_temperature" in n for n in names)


def test_ablation_config_builder_save(tmp_path):
    builder = AblationConfigBuilder(CONFIG_PATH)
    builder.sweep("memory.top_k", [1, 3]).fix("vlm.backend", "stub")
    paths = builder.save_all(tmp_path / "ablation_configs")
    assert len(paths) == 2
    for p in paths:
        assert Path(p).exists()


def test_ablation_runner_stub(tmp_path):
    builder = AblationConfigBuilder(CONFIG_PATH)
    builder.fix("vlm.backend", "stub")
    builder.fix("embeddings.backend", "stub")
    builder.fix("perception.backend", "stub")
    builder.fix("robot.backend", "stub")
    builder.fix("vlm.detector_mode", "always_complete")
    builder.fix("memory.ltm_path", str(tmp_path / "ltm.csv"))
    builder.fix("memory.embeddings_path", str(tmp_path / "ltm.npy"))
    builder.sweep("memory.top_k", [1, 3])

    task = get_task("apple_on_plate_container", table="table_2")
    runner = AblationRunner(builder, tasks=[task], n_trials=2, conditions=["pragmabot"])
    results = runner.run(str(tmp_path / "results"))
    assert len(results) == 2
    for run_name, payload in results.items():
        trials = list(Path(payload["run_dir"], "trials").glob("*.json"))
        assert trials, f"no trials written for {run_name}"

    csv_path = runner.generate_comparison_csv(results, str(tmp_path / "results" / "comparison.csv"))
    assert csv_path.exists()


# ---------------------------------------------------------------------------
# Baselines
# ---------------------------------------------------------------------------


def test_cap_v_baseline_no_stm(tmp_path):
    cfg = _stub_cfg(tmp_path)
    vlm = StubVLM()
    baseline = CaPVBaseline(vlm, cfg)
    assert isinstance(baseline, BaseBaseline)
    action = baseline.plan(
        instruction="pick the apple",
        image=np.zeros((10, 10, 3), dtype=np.uint8),
        available_skills=["pick", "place", "push"],
    )
    assert action["skill"] in {"pick", "place", "push"}
    # The prompt the VLM saw must contain the "no prior actions in this run" marker.
    assert any("no prior actions" in p.lower() for p in vlm.received_prompts)


def test_come_baseline_no_ltm(tmp_path):
    cfg = _stub_cfg(tmp_path)
    vlm = StubVLM()
    baseline = COMEBaseline(vlm, cfg)
    assert baseline.baseline_name == "come"
    baseline.plan("pick the apple", np.zeros((10, 10, 3), dtype=np.uint8), ["pick"])
    # No LTM section means no "past relevant experiences" string should be injected.
    for prompt in vlm.received_prompts:
        assert "past relevant experiences" not in prompt.lower()


def test_baseline_factory(tmp_path):
    cfg = _stub_cfg(tmp_path)
    vlm = StubVLM()
    for name, cls in (("cap_v", CaPVBaseline), ("come", COMEBaseline)):
        baseline = get_baseline(name, vlm=vlm, cfg=cfg)
        assert isinstance(baseline, cls)


# ---------------------------------------------------------------------------
# Reproducibility utils
# ---------------------------------------------------------------------------


def test_config_hash_deterministic(tmp_path):
    cfg = _stub_cfg(tmp_path)
    assert config_hash(cfg) == config_hash(cfg)


def test_config_hash_changes(tmp_path):
    cfg_a = _stub_cfg(tmp_path)
    cfg_b = _stub_cfg(tmp_path)
    cfg_b.pipeline.max_steps = 99
    assert config_hash(cfg_a) != config_hash(cfg_b)


def test_assert_backends_available_stub(tmp_path):
    cfg = _stub_cfg(tmp_path)
    # No exception expected — all stubs are registered.
    assert_backends_available(cfg)


def test_assert_backends_available_unknown(tmp_path):
    cfg = _stub_cfg(tmp_path)
    cfg.vlm.backend = "definitely_not_a_real_backend"
    with pytest.raises(RuntimeError, match=r"unavailable"):
        assert_backends_available(cfg)


def test_get_system_info_keys():
    info = get_system_info()
    for key in ("python_version", "platform", "torch_version",
                "cuda_available", "ros_version", "pragmabot_commit"):
        assert key in info


def test_save_run_metadata(tmp_path):
    cfg = _stub_cfg(tmp_path)
    out = save_run_metadata(cfg, tmp_path / "run.json")
    payload = json.loads(out.read_text())
    assert payload["config_hash"]
    assert "timestamp" in payload
    assert "system_info" in payload
    assert "config" in payload


# ---------------------------------------------------------------------------
# Visualization
# ---------------------------------------------------------------------------


def test_viz_success_rates(tmp_path):
    out = plot_success_rates(
        {"apple": {"cap_v": 0.4, "pragmabot": 0.9}, "candy": {"cap_v": 0.2, "pragmabot": 0.7}},
        tmp_path / "success.png",
    )
    assert out.exists()
    assert out.stat().st_size > 0


def test_viz_timing_breakdown(tmp_path):
    trials = [
        {
            "task_name": "apple",
            "per_step_timings": {
                "mean_planning_time_sec": 0.5,
                "mean_execution_time_sec": 1.0,
                "mean_detection_time_sec": 0.3,
            },
        },
        {
            "task_name": "candy",
            "per_step_timings": {
                "mean_planning_time_sec": 0.6,
                "mean_execution_time_sec": 1.2,
                "mean_detection_time_sec": 0.4,
            },
        },
    ]
    out = plot_timing_breakdown(trials, tmp_path / "timing.png")
    assert out.exists()


# ---------------------------------------------------------------------------
# Docs presence
# ---------------------------------------------------------------------------


def test_extension_guide_exists():
    text = (REPO_ROOT / "docs" / "EXTENSION_GUIDE.md").read_text(encoding="utf-8")
    assert "Adding a new VLM backend" in text


def test_reproduction_guide_exists():
    assert (REPO_ROOT / "docs" / "REPRODUCTION_GUIDE.md").exists()


def test_architecture_doc_exists():
    assert (REPO_ROOT / "docs" / "ARCHITECTURE.md").exists()


def test_makefile_exists():
    text = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    for target in ("test-mac:", "smoke-mac:", "eval-stub:", "ablation-stub:"):
        assert target in text


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
