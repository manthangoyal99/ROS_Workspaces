"""[MAC] Phase 3 smoke — perception layer + annotation overlay + pipeline integration."""

from __future__ import annotations

import logging
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
PKG_SRC = REPO_ROOT / "pragmabot" / "src"
if str(PKG_SRC) not in sys.path:
    sys.path.insert(0, str(PKG_SRC))

from pragmabot.perception import (  # noqa: E402
    ImageAnnotator,
    StubPerception,
)
from pragmabot.pipeline import PragmaBot  # noqa: E402
from pragmabot.simple_config import load_config  # noqa: E402


class CountingPerception(StubPerception):
    """Stub perception that counts detect() calls — for the smoke test."""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def detect(self, rgb, queries, depth=None):
        self.calls += 1
        return super().detect(rgb, queries, depth=depth)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

    cfg = load_config(REPO_ROOT / "pragmabot" / "config" / "config.yaml")
    cfg.vlm.backend = "stub"
    cfg.embeddings.backend = "stub"
    cfg.robot.backend = "stub"
    cfg.perception.backend = "stub"
    cfg.pipeline.max_steps = 2
    cfg.vlm.detector_mode = "complete_at:1"
    tmp = Path(tempfile.mkdtemp(prefix="pragmabot_phase3_"))
    cfg.memory.ltm_path = str(tmp / "ltm.csv")
    cfg.memory.embeddings_path = str(tmp / "ltm_embeddings.npy")

    # 1. StubPerception
    perception = StubPerception()
    image = np.zeros((480, 640, 3), dtype=np.uint8)
    result = perception.detect(image, ["apple", "can", "plate"])
    print("--- detected objects ---")
    for obj in result.objects:
        c3 = None if obj.centroid_3d is None else [round(float(x), 3) for x in obj.centroid_3d]
        print(
            f"  {obj.name}: conf={obj.confidence:.2f} "
            f"bbox={obj.bbox_2d} centroid_2d={obj.centroid_2d} centroid_3d={c3}"
        )

    # 2. Annotation
    annotator = ImageAnnotator()
    first = result.objects[0]
    candidates = annotator.generate_push_candidates(
        first.centroid_2d, n_directions=4, distance_px=80
    )
    annotated = annotator.annotate_mask(image, first.mask, color=(0, 255, 0), alpha=0.4)
    annotated = annotator.annotate_candidates(annotated, candidates, style="circle")
    annotated = annotator.draw_bbox(annotated, first.bbox_2d, label=first.name)

    out_path = Path("/tmp/phase3_annotation.png")
    Image.fromarray(annotated, mode="RGB").save(out_path)
    print(f"Annotation saved to {out_path}")

    # 3. Pipeline with counting perception
    counting = CountingPerception()
    bot = PragmaBot(cfg, perception=counting)
    pipeline_result = bot.run_task("pick up the apple")
    print(
        "Pipeline:",
        {
            "success": pipeline_result["success"],
            "steps": pipeline_result["steps"],
            "perception_queries": pipeline_result["perception_queries"],
        },
    )
    assert counting.calls >= 1, "perception was not invoked from the pipeline"
    print(f"perception.detect() was called {counting.calls} time(s).")

    print("Phase 3 Mac smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
