"""[MAC] Phase 5 smoke — full pipeline integration with stubs + episode logs."""

from __future__ import annotations

import json
import logging
import statistics
import sys
import tempfile
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
PKG_SRC = REPO_ROOT / "pragmabot" / "src"
if str(PKG_SRC) not in sys.path:
    sys.path.insert(0, str(PKG_SRC))

from pragmabot.pipeline import PragmaBot  # noqa: E402
from pragmabot.simple_config import load_config  # noqa: E402
from pragmabot.vlm.stub_vlm import StubVLM  # noqa: E402


class CountingVLM(StubVLM):
    """StubVLM with a configurable failure step (for the graceful-error case)."""

    def __init__(self, fail_on_call: int = -1, **kw):
        super().__init__(**kw)
        self.fail_on_call = int(fail_on_call)
        self._call = 0

    def chat_with_image(self, messages, images):
        self._call += 1
        if self._call == self.fail_on_call:
            raise RuntimeError(f"injected failure on call #{self._call}")
        return super().chat_with_image(messages, images)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

    cfg = load_config(REPO_ROOT / "pragmabot" / "config" / "config.yaml")
    cfg.vlm.backend = "stub"
    cfg.embeddings.backend = "stub"
    cfg.robot.backend = "stub"
    cfg.perception.backend = "stub"
    cfg.pipeline.max_steps = 2
    cfg.vlm.detector_mode = "always_complete"
    tmp = Path(tempfile.mkdtemp(prefix="pragmabot_phase5_"))
    cfg.memory.ltm_path = str(tmp / "ltm.csv")
    cfg.memory.embeddings_path = str(tmp / "ltm_embeddings.npy")
    cfg.logging.log_dir = str(tmp / "logs")

    callbacks_seen = []
    bot = PragmaBot(cfg, step_callback=callbacks_seen.append)

    # 1) Two successful runs back-to-back.
    r1 = bot.run_task("pick up the apple")
    r2 = bot.run_task("move the can")
    print(f"task 1: success={r1['success']} steps={r1['steps']} log={r1['episode_log_path']}")
    print(f"task 2: success={r2['success']} steps={r2['steps']} log={r2['episode_log_path']}")
    assert Path(r1["episode_log_path"]).exists()
    assert Path(r2["episode_log_path"]).exists()
    assert len(bot.memory) == 2, f"LTM expected 2 entries, got {len(bot.memory)}"
    assert len(callbacks_seen) >= 6, "step_callback was not invoked enough times"
    print(f"step_callback invoked {len(callbacks_seen)} times across two tasks.")

    # 2) Mid-task injected error → graceful failure with a partial log.
    fail_vlm = CountingVLM(fail_on_call=3)
    bot2 = PragmaBot(cfg, vlm=fail_vlm)
    r3 = bot2.run_task("pick up the apple")
    print(f"task 3 (with injected failure): success={r3['success']} error={r3['error']!r}")
    assert r3["success"] is False
    assert r3["error"]
    assert Path(r3["episode_log_path"]).exists()

    # 3) Timing stats.
    planning, execution, detection, perception = [], [], [], []
    for result in (r1, r2):
        for entry in result["stm"]:
            t = entry["feedback"]["_timings"]
            planning.append(t["planning_time_sec"])
            execution.append(t["execution_time_sec"])
            detection.append(t["detection_time_sec"])
            perception.append(t["perception_time_sec"])

    def _stats(xs):
        if not xs:
            return "n=0"
        return f"n={len(xs)} mean={statistics.mean(xs):.4f}s max={max(xs):.4f}s"

    print("--- timing stats (stub backends) ---")
    print(f"planning:   {_stats(planning)}")
    print(f"execution:  {_stats(execution)}")
    print(f"detection:  {_stats(detection)}")
    print(f"perception: {_stats(perception)}")

    # Sanity-check the first episode log has the expected fields.
    payload = json.loads(Path(r1["episode_log_path"]).read_text())
    required = {"episode_id", "instruction", "stm", "config_snapshot",
                "scenario_key", "experience_stored"}
    missing = required - payload.keys()
    assert not missing, f"missing fields in episode log: {missing}"
    print(f"episode log fields OK ({len(payload['stm'])} steps recorded).")

    print("Phase 5 Mac smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
