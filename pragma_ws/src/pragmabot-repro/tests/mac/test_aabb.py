"""Mac tests for the AABB utility."""

from __future__ import annotations

import json

import numpy as np
import pytest

from pragmabot.perception import (
    AxisAlignedBoundingBox,
    CameraIntrinsics,
    compute_aabb_from_mask_depth,
    compute_aabb_from_points,
)


def _make_intrinsics() -> CameraIntrinsics:
    return CameraIntrinsics(fx=600.0, fy=600.0, cx=320.0, cy=240.0,
                             width=640, height=480, depth_scale=1.0)


def test_compute_aabb_from_points_basic():
    """Box-shaped cloud yields correct extents and 8 corners."""
    rng = np.random.default_rng(0)
    hx, hy, hz = 0.05, 0.03, 0.02
    pts = rng.uniform(low=[-hx, -hy, -hz], high=[+hx, +hy, +hz], size=(4000, 3))
    aabb = compute_aabb_from_points(pts, frame="test")
    assert isinstance(aabb, AxisAlignedBoundingBox)
    assert aabb.corners.shape == (8, 3)
    assert aabb.top_face_corners.shape == (4, 3)
    # Extents within tolerance (percentile clip trims edges, so the box is slightly
    # smaller than 2*hx).
    assert aabb.depth_x_m  == pytest.approx(2 * hx, abs=5e-3)
    assert aabb.width_y_m  == pytest.approx(2 * hy, abs=5e-3)
    assert aabb.height_z_m == pytest.approx(2 * hz, abs=5e-3)
    assert aabb.length_horiz_m == pytest.approx(2 * hx, abs=5e-3)
    assert aabb.width_horiz_m  == pytest.approx(2 * hy, abs=5e-3)


def test_aabb_corner_ordering_canonical():
    """Same ordering as OBB: bottom face CCW + top above bottom."""
    rng = np.random.default_rng(1)
    pts = rng.uniform(low=[-0.05, -0.03, -0.02], high=[0.05, 0.03, 0.02], size=(3000, 3))
    aabb = compute_aabb_from_points(pts, frame="test")
    for i in range(4):
        bot = aabb.corners[i]
        top = aabb.corners[i + 4]
        assert np.allclose(bot[:2], top[:2], atol=1e-9)
        assert top[2] > bot[2]
    # Bottom face follows (xmin,ymin) -> (xmax,ymin) -> (xmax,ymax) -> (xmin,ymax).
    bot = aabb.corners[:4]
    assert bot[0, 0] < bot[1, 0]  # +x edge
    assert bot[1, 1] < bot[2, 1]  # +y edge
    assert bot[2, 0] > bot[3, 0]  # -x edge
    assert bot[3, 1] > bot[0, 1]  # -y edge


def test_aabb_from_mask_depth_top_view():
    """Project a horizontal box, recover its AABB (height collapses)."""
    intr = _make_intrinsics()
    h, w = intr.height, intr.width
    # 80mm x 50mm patch at z = 0.5m, centered.
    mask = np.zeros((h, w), dtype=bool)
    depth = np.zeros((h, w), dtype=np.float32)
    cx, cy, z_m = intr.cx, intr.cy, 0.5
    half_w_px = int(round(intr.fx * 0.04 / z_m))
    half_h_px = int(round(intr.fy * 0.025 / z_m))
    u_lo, u_hi = int(cx - half_w_px), int(cx + half_w_px)
    v_lo, v_hi = int(cy - half_h_px), int(cy + half_h_px)
    mask[v_lo:v_hi, u_lo:u_hi] = True
    depth[v_lo:v_hi, u_lo:u_hi] = z_m
    aabb = compute_aabb_from_mask_depth(mask, depth, intr, min_points=50)
    assert aabb is not None
    # Extents along camera x and y should match the patch size.
    assert aabb.extents[0] == pytest.approx(0.08, abs=5e-3)
    assert aabb.extents[1] == pytest.approx(0.05, abs=5e-3)
    # Single depth plane -> z extent is ~0.
    assert aabb.extents[2] < 1e-3


def test_aabb_empty_returns_none():
    intr = _make_intrinsics()
    mask = np.zeros((intr.height, intr.width), dtype=bool)
    depth = np.zeros((intr.height, intr.width), dtype=np.float32)
    assert compute_aabb_from_mask_depth(mask, depth, intr, min_points=30) is None


def test_aabb_to_dict_serializable():
    rng = np.random.default_rng(2)
    pts = rng.uniform(low=[-0.05, -0.03, -0.02], high=[0.05, 0.03, 0.02], size=(2000, 3))
    aabb = compute_aabb_from_points(pts, frame="panda_link0")
    d = aabb.to_dict()
    json.dumps(d)  # round-trip safe
    for key in (
        "frame", "center_m", "min_xyz_m", "max_xyz_m", "extents_m",
        "depth_x_m", "width_y_m", "height_z_m",
        "length_horiz_m", "width_horiz_m",
        "corners_m", "top_face_corners_m", "n_points_used", "corner_order",
    ):
        assert key in d, f"missing {key}"
    assert len(d["corners_m"]) == 8
    assert len(d["top_face_corners_m"]) == 4
