"""[MAC] Phase 7 smoke — registry inventory, ablation run, docs check, viz."""

from __future__ import annotations

import logging
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PKG_SRC = REPO_ROOT / "pragmabot" / "src"
if str(PKG_SRC) not in sys.path:
    sys.path.insert(0, str(PKG_SRC))

import numpy as np  # noqa: E402

from pragmabot.ablation import AblationConfigBuilder, AblationRunner  # noqa: E402
from pragmabot.eval import get_task  # noqa: E402
from pragmabot.pipeline import PragmaBot  # noqa: E402
from pragmabot.registry import registry  # noqa: E402
from pragmabot.simple_config import load_config  # noqa: E402
from pragmabot.utils.reproducibility import (  # noqa: E402
    assert_backends_available,
    config_hash,
    save_run_metadata,
)
from pragmabot.utils.viz import (  # noqa: E402
    plot_ltm_retrieval_heatmap,
    plot_stm_length_vs_success,
    plot_success_rates,
    plot_timing_breakdown,
)


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")

    tmp = Path(tempfile.mkdtemp(prefix="pragmabot_phase7_"))

    print("Registry backends:")
    for ctype in sorted(registry.list_component_types()):
        names = registry.list_available(ctype)
        print(f"  {ctype:11s}: {', '.join(names) if names else '(none)'}")

    cfg = load_config(REPO_ROOT / "pragmabot" / "config" / "config.yaml")
    cfg.vlm.backend = "stub"
    cfg.embeddings.backend = "stub"
    cfg.perception.backend = "stub"
    cfg.robot.backend = "stub"
    cfg.memory.ltm_path = str(tmp / "ltm.csv")
    cfg.memory.embeddings_path = str(tmp / "ltm.npy")
    cfg.logging.log_dir = str(tmp / "logs")
    cfg.pipeline.max_steps = 1
    cfg.vlm.detector_mode = "always_complete"

    assert_backends_available(cfg)
    print(f"config_hash = {config_hash(cfg)}")
    save_run_metadata(cfg, tmp / "run_metadata.json")

    builder = AblationConfigBuilder(REPO_ROOT / "pragmabot" / "config" / "config.yaml")
    for k, v in (
        ("vlm.backend", "stub"),
        ("embeddings.backend", "stub"),
        ("perception.backend", "stub"),
        ("robot.backend", "stub"),
        ("vlm.detector_mode", "always_complete"),
        ("memory.ltm_path", str(tmp / "abl_ltm.csv")),
        ("memory.embeddings_path", str(tmp / "abl_ltm.npy")),
    ):
        builder.fix(k, v)
    builder.sweep("memory.top_k", [1, 3])

    task = get_task("apple_on_plate_container", table="table_2")
    ablation_runner = AblationRunner(builder, tasks=[task], n_trials=2, conditions=["pragmabot"])
    results = ablation_runner.run(str(tmp / "ablation"))
    ablation_runner.summarize(results)
    csv = ablation_runner.generate_comparison_csv(results, str(tmp / "ablation" / "comparison.csv"))
    print(f"Comparison CSV: {csv}")

    # Docs presence
    for name in ("EXTENSION_GUIDE.md", "REPRODUCTION_GUIDE.md", "ARCHITECTURE.md"):
        path = REPO_ROOT / "docs" / name
        assert path.exists(), f"missing {path}"
        print(f"OK  docs/{name}")

    # Visualizations to /tmp (degrade gracefully if matplotlib is missing).
    viz_ok = True
    try:
        plot_success_rates(
            {task.name: {"cap_v": 0.4, "pragmabot": 0.9}},
            "/tmp/phase7_success.png",
        )
        plot_timing_breakdown(
            [
                {"task_name": "apple", "per_step_timings": {
                    "mean_planning_time_sec": 0.5, "mean_execution_time_sec": 1.0,
                    "mean_detection_time_sec": 0.3,
                }},
            ],
            "/tmp/phase7_timing.png",
        )
        plot_stm_length_vs_success(
            [{"steps": 1, "success": True}, {"steps": 2, "success": False}],
            "/tmp/phase7_stm.png",
        )
        bot = PragmaBot(cfg)
        bot.memory.store("hello world", "experience")
        plot_ltm_retrieval_heatmap(bot.memory, "/tmp/phase7_heatmap.png")
        print("Visualizations saved to /tmp/phase7_*.png")
    except ModuleNotFoundError as exc:
        viz_ok = False
        print(f"WARNING: matplotlib unavailable, skipping plots ({exc}).")
        print("         Install with: pip install matplotlib")

    # Run pytest tests/mac/test_full_suite.py as a subprocess to keep this script idempotent.
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/mac/test_full_suite.py", "-q"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=120,
    )
    full_pipeline_ok = completed.returncode == 0
    if not full_pipeline_ok:
        print(completed.stdout)
        print(completed.stderr)
    assert full_pipeline_ok, "test_full_mac_pipeline failed"

    print()
    print("=== PragmaBot Phase 7 Readiness Report ===")
    print("Registry backends:")
    for ctype in sorted(registry.list_component_types()):
        print(f"  {ctype:11s}: {', '.join(registry.list_available(ctype)) or '(none)'}")
    print()
    print("Mac smoke tests:    PASS")
    print("Full pipeline test: PASS")
    print("Ablation runner:    PASS")
    print("Documentation:      PASS")
    print(f"Visualizations:     {'PASS' if viz_ok else 'SKIP (matplotlib not installed)'}")
    print()
    print("Phase 7 complete. Repository is research-ready.")
    print("Phase 7 Mac smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
