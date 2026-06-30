"""[MAC] Phase 1 smoke script — full pipeline with stub backends + LTM growth."""

from __future__ import annotations

import json
import logging
import sys
import tempfile
from pathlib import Path

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

    cfg.vlm.backend = "stub"
    cfg.embeddings.backend = "stub"
    cfg.robot.backend = "stub"
    cfg.pipeline.max_steps = 3
    cfg.vlm.detector_mode = "complete_at:2"
    tmp = Path(tempfile.mkdtemp(prefix="pragmabot_phase1_"))
    cfg.memory.ltm_path = str(tmp / "ltm.csv")
    cfg.memory.embeddings_path = str(tmp / "ltm_embeddings.npy")

    bot = PragmaBot(cfg)
    print(f"LTM entries before any task: {len(bot.memory)}")

    result_1 = bot.run_task("put the apple on the plate")
    print("--- task 1 result ---")
    print(json.dumps(result_1, indent=2, default=str))
    print(f"LTM entries after task 1: {len(bot.memory)}")

    # Different detector behaviour for the second task — succeed on the first call.
    bot.vlm.detector_mode = "always_complete"
    result_2 = bot.run_task("move the can to the left")
    print("--- task 2 result ---")
    print(json.dumps(result_2, indent=2, default=str))
    print(f"LTM entries after task 2: {len(bot.memory)}")

    assert len(bot.memory) == 2, "LTM did not grow as expected"
    print("Phase 1 smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
