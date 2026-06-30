"""Phase 3 Mac tests — perception layer + camera geometry + annotation."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from omegaconf import OmegaConf

from pragmabot.perception import (
    BasePerception,
    CameraIntrinsics,
    DetectedObject,
    ImageAnnotator,
    PerceptionResult,
    StubPerception,
    farthest_point_sample,
    get_perception,
    unproject_pixel,
)
from pragmabot.perception.camera_intrinsics import unproject_mask
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
    return cfg


def _black_image(h: int = 480, w: int = 640) -> np.ndarray:
    return np.zeros((h, w, 3), dtype=np.uint8)


# ---------------------------------------------------------------------------
# Stub perception
# ---------------------------------------------------------------------------


def test_stub_perception_returns_result():
    p = StubPerception()
    result = p.detect(_black_image(), ["apple"])
    assert isinstance(result, PerceptionResult)
    assert len(result.objects) == 1
    obj = result.objects[0]
    assert obj.name == "apple"
    assert obj.confidence > 0.0
    assert len(obj.bbox_2d) == 4
    assert obj.mask is not None and obj.mask.shape == (480, 640)


def test_stub_perception_multi_query():
    p = StubPerception()
    result = p.detect(_black_image(), ["apple", "can", "plate"])
    assert len(result.objects) == 3
    centroids = [obj.centroid_2d for obj in result.objects]
    # All three centroids must be distinct.
    assert len(set(centroids)) == 3


def test_stub_perception_deterministic():
    p = StubPerception()
    r1 = p.detect(_black_image(), ["apple", "can"])
    r2 = p.detect(_black_image(), ["apple", "can"])
    for a, b in zip(r1.objects, r2.objects):
        assert a.name == b.name
        assert a.bbox_2d == b.bbox_2d
        assert a.centroid_2d == b.centroid_2d
        assert np.allclose(a.centroid_3d, b.centroid_3d)


def test_detected_object_fields():
    p = StubPerception()
    obj = p.detect(_black_image(), ["apple"]).objects[0]
    assert isinstance(obj, DetectedObject)
    assert isinstance(obj.name, str)
    assert isinstance(obj.confidence, float)
    assert isinstance(obj.bbox_2d, tuple) and len(obj.bbox_2d) == 4
    assert isinstance(obj.centroid_2d, tuple) and len(obj.centroid_2d) == 2
    assert isinstance(obj.centroid_3d, np.ndarray) and obj.centroid_3d.shape == (3,)
    assert isinstance(obj.extras, dict)


def test_perception_result_get_object():
    p = StubPerception()
    result = p.detect(_black_image(), ["apple", "can"])
    assert result.get_object("Apple") is result.objects[0]
    assert result.get_all("can") == [result.objects[1]]


def test_perception_result_get_object_missing():
    p = StubPerception()
    result = p.detect(_black_image(), ["apple"])
    assert result.get_object("xyz") is None
    assert result.get_all("xyz") == []


# ---------------------------------------------------------------------------
# Camera geometry
# ---------------------------------------------------------------------------


def test_unproject_pixel():
    intr = CameraIntrinsics(fx=300.0, fy=300.0, cx=320.0, cy=240.0, width=640, height=480, depth_scale=0.001)
    # 1 m depth at the principal point projects to (0, 0, 1).
    depth = np.full((480, 640), 1000, dtype=np.uint16)
    point = unproject_pixel(320, 240, depth, intr)
    assert point is not None
    assert np.allclose(point, [0.0, 0.0, 1.0], atol=1e-6)

    # 1 m depth at (cx + fx, cy) should give x = 1 m.
    point2 = unproject_pixel(320 + 300, 240, depth, intr)
    assert point2 is not None
    assert np.allclose(point2, [1.0, 0.0, 1.0], atol=1e-6)


def test_unproject_pixel_zero_depth():
    intr = CameraIntrinsics(fx=500.0, fy=500.0, cx=320.0, cy=240.0, width=640, height=480)
    depth = np.zeros((480, 640), dtype=np.uint16)
    assert unproject_pixel(320, 240, depth, intr) is None


def test_unproject_mask_centroid():
    intr = CameraIntrinsics(fx=500.0, fy=500.0, cx=320.0, cy=240.0, width=640, height=480, depth_scale=0.001)
    depth = np.full((480, 640), 1000, dtype=np.uint16)
    mask = np.zeros((480, 640), dtype=bool)
    mask[200:280, 280:360] = True
    point = unproject_mask(mask, depth, intr, method="centroid")
    assert point is not None
    assert np.allclose(point, [0.0, 0.0, 1.0], atol=1e-6)


def test_farthest_point_sample():
    rng = np.random.default_rng(0)
    pts = rng.integers(0, 1000, size=(100, 2))
    idx = farthest_point_sample(pts, 5)
    assert idx.shape == (5,)
    assert len(set(idx.tolist())) == 5  # distinct
    assert (idx >= 0).all() and (idx < 100).all()


# ---------------------------------------------------------------------------
# Annotator
# ---------------------------------------------------------------------------


def test_annotator_candidates():
    ann = ImageAnnotator()
    img = np.zeros((100, 200, 3), dtype=np.uint8)
    out = ann.annotate_candidates(img, [(50, 50), (150, 50)], style="circle")
    assert out.shape == img.shape
    assert out.dtype == np.uint8
    # Non-zero pixels should appear where we drew the markers.
    assert out.sum() > 0
    # And the original image must be untouched (no in-place edit).
    assert img.sum() == 0


def test_annotator_push_candidates():
    out = ImageAnnotator.generate_push_candidates((100, 100), n_directions=4, distance_px=80)
    assert len(out) == 4
    for pt in out:
        assert isinstance(pt, tuple) and len(pt) == 2
    # The four endpoints should be roughly 80px from the centroid.
    for u, v in out:
        d = np.linalg.norm(np.array([u - 100, v - 100]))
        assert abs(d - 80) < 2


def test_annotator_mask_overlay():
    ann = ImageAnnotator()
    img = np.zeros((40, 60, 3), dtype=np.uint8)
    mask = np.zeros((40, 60), dtype=bool)
    mask[10:30, 20:40] = True
    out = ann.annotate_mask(img, mask, color=(0, 255, 0), alpha=0.5)
    assert out.shape == img.shape
    # Green channel should be non-zero where the mask is set.
    assert out[20, 30, 1] > 0
    assert out[0, 0, 1] == 0


def test_annotator_bbox_returns_same_shape():
    ann = ImageAnnotator()
    img = np.zeros((40, 60, 3), dtype=np.uint8)
    out = ann.draw_bbox(img, (5, 5, 30, 30), label="apple")
    assert out.shape == img.shape


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def test_perception_factory_stub(tmp_path):
    cfg = _stub_cfg(tmp_path)
    p = get_perception(cfg)
    assert isinstance(p, StubPerception)
    assert p.backend_name == "stub"


def test_grounded_sam_unavailable_error(tmp_path):
    cfg = _stub_cfg(tmp_path)
    cfg.perception.backend = "grounded_sam"
    # Mac has no torch / SAM installed, so GROUNDED_SAM_AVAILABLE is False.
    from pragmabot.perception.grounded_sam import GROUNDED_SAM_AVAILABLE

    if GROUNDED_SAM_AVAILABLE:
        pytest.skip("Grounded SAM is available on this machine — clear-message check N/A.")
    with pytest.raises(RuntimeError, match="grounded_sam"):
        get_perception(cfg)


# ---------------------------------------------------------------------------
# Pipeline integration
# ---------------------------------------------------------------------------


class CountingPerception(StubPerception):
    """Stub perception that counts detect() calls."""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def detect(self, rgb, queries, depth=None):
        self.calls += 1
        return super().detect(rgb, queries, depth=depth)


def test_pipeline_uses_perception(tmp_path):
    cfg = _stub_cfg(tmp_path)
    cfg.pipeline.max_steps = 3
    cfg.vlm.detector_mode = "complete_at:2"
    perception = CountingPerception()
    bot = PragmaBot(cfg, perception=perception)
    result = bot.run_task("pick up the apple")
    assert result["success"] is True
    assert perception.calls >= 1, "perception.detect() was not called"
    # One detect() per step.
    assert perception.calls >= result["steps"]


class AnnotationCapture(StubPerception):
    pass


def test_pipeline_annotation_flow(tmp_path):
    cfg = _stub_cfg(tmp_path)
    cfg.pipeline.max_steps = 1
    cfg.vlm.detector_mode = "always_complete"
    # Make the stub planner emit ``use_annotation: true`` and a push action so
    # the pipeline triggers the FPS / push-candidate refinement branch.
    cfg.vlm.planner_skill = "push"
    cfg.vlm.planner_object = "apple"

    bot = PragmaBot(cfg)

    # Monkey-patch the stub VLM to inject use_annotation into its planner JSON.
    original = bot.vlm._planner_response

    def patched():
        import json as _json

        payload = _json.loads(original())
        payload["parameters"]["use_annotation"] = True
        return _json.dumps(payload)

    bot.vlm._planner_response = patched  # type: ignore[assignment]

    result = bot.run_task("push the apple away")
    assert result["success"] is True
    assert result["annotated_image_shape"] is not None
    h, w, c = result["annotated_image_shape"]
    assert c == 3
    assert h > 0 and w > 0


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
