"""[MAC] Phase 0 smoke script.

Runs the full PragmaBot pipeline against stub backends, then exercises LTM
store + retrieve so the end-to-end path is verified.

Usage:
    python scripts/smoke_phase0.py
"""

from __future__ import annotations

import json
import logging
import sys
import tempfile
from pathlib import Path

import numpy as np

# Make the pragmabot package importable when running from the repo root.
REPO_ROOT = Path(__file__).resolve().parent.parent
PKG_SRC = REPO_ROOT / "pragmabot" / "src"
if str(PKG_SRC) not in sys.path:
    sys.path.insert(0, str(PKG_SRC))

from pragmabot.pipeline import PragmaBot  # noqa: E402
from pragmabot.simple_config import load_config  # noqa: E402


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

    cfg_path = REPO_ROOT / "pragmabot" / "config" / "config.yaml"
    cfg = load_config(cfg_path)

    # Force stub backends for the smoke test, and isolate persistence to /tmp.
    cfg.vlm.backend = "stub"
    cfg.embeddings.backend = "stub"
    cfg.robot.backend = "stub"
    cfg.pipeline.max_steps = 2
    tmp = Path(tempfile.mkdtemp(prefix="pragmabot_smoke_"))
    cfg.memory.ltm_path = str(tmp / "ltm.csv")
    cfg.memory.embeddings_path = str(tmp / "ltm_embeddings.npy")

    bot = PragmaBot(cfg)

    def get_observation():
        return np.zeros((480, 640, 3), dtype=np.uint8)

    result = bot.run_task("pick up the apple", get_observation)
    print("--- pipeline result ---")
    print(json.dumps(result, indent=2, default=str))

    bot.memory.store(
        "pick up the apple from the table",
        "Successfully picked the apple after one attempt.",
    )
    retrieved = bot.memory.retrieve("pick up the apple", top_k=1)
    print("--- ltm retrieval ---")
    print(json.dumps(retrieved, indent=2, default=str))

    print("Phase 0 smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
