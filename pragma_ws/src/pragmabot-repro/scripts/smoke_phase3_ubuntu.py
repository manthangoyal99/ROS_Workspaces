"""[UBUNTU] Phase 3 smoke — try Grounded SAM if available, else fall back to stub."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import numpy as np
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
PKG_SRC = REPO_ROOT / "pragmabot" / "src"
if str(PKG_SRC) not in sys.path:
    sys.path.insert(0, str(PKG_SRC))

from pragmabot.perception import StubPerception  # noqa: E402
from pragmabot.perception.factory import get_perception  # noqa: E402
from pragmabot.simple_config import load_config  # noqa: E402


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    cfg = load_config(REPO_ROOT / "pragmabot" / "config" / "config.yaml")

    from pragmabot.perception.grounded_sam import GROUNDED_SAM_AVAILABLE

    mode = "real" if GROUNDED_SAM_AVAILABLE else "stub"
    print(f"GROUNDED_SAM_AVAILABLE = {GROUNDED_SAM_AVAILABLE} (mode={mode})")

    if GROUNDED_SAM_AVAILABLE:
        cfg.perception.backend = "grounded_sam"
        try:
            perception = get_perception(cfg)
        except FileNotFoundError as exc:
            print(f"Grounded SAM checkpoints missing ({exc}); falling back to stub.")
            mode = "stub"
            perception = StubPerception()
    else:
        perception = StubPerception()

    # A solid test image: a synthetic 480x640 RGB with one bright square.
    image = np.zeros((480, 640, 3), dtype=np.uint8)
    image[200:280, 280:360] = (255, 64, 64)

    queries = ["apple", "red square", "object"]
    result = perception.detect(image, queries)
    print(f"Detected {len(result.objects)} objects with {perception.backend_name}.")
    for obj in result.objects:
        print(f"  - {obj.name}: bbox={obj.bbox_2d}, confidence={obj.confidence:.2f}")

    Image.fromarray(image, mode="RGB").save("/tmp/phase3_test_image.png")
    print(f"Phase 3 Ubuntu smoke test passed (mode: {mode})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
