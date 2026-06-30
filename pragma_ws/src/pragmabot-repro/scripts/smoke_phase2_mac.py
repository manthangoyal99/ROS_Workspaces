"""[MAC] Phase 2 smoke — verify the pipeline works with an injected observation source."""

from __future__ import annotations

import json
import logging
import sys
import tempfile
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
PKG_SRC = REPO_ROOT / "pragmabot" / "src"
if str(PKG_SRC) not in sys.path:
    sys.path.insert(0, str(PKG_SRC))

# Importing the pipeline must NOT fail just because ROS is missing.
from pragmabot.pipeline import PragmaBot  # noqa: E402
from pragmabot.simple_config import load_config  # noqa: E402


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

    cfg = load_config(REPO_ROOT / "pragmabot" / "config" / "config.yaml")
    cfg.vlm.backend = "stub"
    cfg.embeddings.backend = "stub"
    cfg.robot.backend = "stub"
    cfg.pipeline.max_steps = 2
    cfg.vlm.detector_mode = "complete_at:1"

    tmp = Path(tempfile.mkdtemp(prefix="pragmabot_phase2_"))
    cfg.memory.ltm_path = str(tmp / "ltm.csv")
    cfg.memory.embeddings_path = str(tmp / "ltm_embeddings.npy")

    bot = PragmaBot(cfg)

    rng = np.random.default_rng(42)
    calls = {"n": 0}

    def fake_obs():
        calls["n"] += 1
        return rng.integers(0, 256, size=(64, 96, 3), dtype=np.uint8)

    bot.robot.set_observation_source(fake_obs)
    assert bot.robot.has_observation_source(), "observation source not registered"

    result = bot.run_task("pick up the mug")
    print(json.dumps(result, indent=2, default=str))

    assert calls["n"] >= 3, f"injected source was not used (calls={calls['n']})"
    print(f"Observation source called {calls['n']} times.")
    print("Phase 2 Mac smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
