"""Phase 3 Ubuntu-only tests — exercise heavy perception deps when available."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

try:
    import torch  # type: ignore  # noqa: F401

    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

pytestmark = pytest.mark.skipif(not TORCH_AVAILABLE, reason="torch not available")


from pragmabot.perception import (  # noqa: E402
    CameraIntrinsics,
    unproject_pixel,
)
from pragmabot.simple_config import load_config  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "pragmabot" / "config" / "config.yaml"


def test_grounded_sam_import():
    """Import path must work even if checkpoints are missing."""
    from pragmabot.perception.grounded_sam import (  # noqa: F401
        GROUNDED_SAM_AVAILABLE,
        GroundedSAMPerception,
    )


def test_grounded_sam_is_available_check():
    from pragmabot.perception.grounded_sam import GROUNDED_SAM_AVAILABLE

    assert isinstance(GROUNDED_SAM_AVAILABLE, bool)


def test_camera_intrinsics_from_config():
    cfg = load_config(CONFIG_PATH)
    intr = CameraIntrinsics.from_config(cfg)
    assert intr.fx == cfg.camera.fx
    assert intr.fy == cfg.camera.fy
    assert intr.cx == cfg.camera.cx
    assert intr.cy == cfg.camera.cy
    assert intr.width == cfg.camera.width
    assert intr.height == cfg.camera.height


def test_unproject_roundtrip():
    intr = CameraIntrinsics(
        fx=615.0, fy=615.0, cx=320.0, cy=240.0, width=640, height=480, depth_scale=0.001
    )
    # Known 3D point in camera frame.
    p = np.array([0.1, -0.05, 0.7], dtype=float)
    pixel = intr.project(p)
    assert pixel is not None
    u, v = int(round(pixel[0])), int(round(pixel[1]))

    # Synthesize a depth map (uint16 in mm) with that depth at (u, v).
    depth = np.zeros((480, 640), dtype=np.uint16)
    depth[v, u] = int(round(p[2] * 1000.0))

    back = unproject_pixel(u, v, depth, intr)
    assert back is not None
    # Allow up to 1 mm of pixel quantization error.
    assert np.linalg.norm(back - p) < 1e-3
