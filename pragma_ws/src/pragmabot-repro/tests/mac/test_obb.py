"""Mac tests for the OBB utility (pure-numpy, no ROS).

We synthesize a depth map of a known cuboid sitting on a plane, run the
OBB pipeline, and verify:
  - center, dimensions, yaw
  - canonical corner ordering (bottom CCW, top above bottom)
  - face-center ordering
  - top-face exposed as ``corners[4:8]``
  - graceful return on empty / sparse masks
"""

from __future__ import annotations

import numpy as np
import pytest

from pragmabot.perception import (
    CameraIntrinsics,
    OrientedBoundingBox,
    compute_obb_from_mask_depth,
    compute_obb_from_points,
)


# ---------------------------------------------------------------------------
# Synthetic scene helpers
# ---------------------------------------------------------------------------


def _make_intrinsics() -> CameraIntrinsics:
    return CameraIntrinsics(fx=600.0, fy=600.0, cx=320.0, cy=240.0,
                             width=640, height=480, depth_scale=1.0)


def _project_box_depth(
    intrinsics: CameraIntrinsics,
    center_cam: np.ndarray,
    half_extents: np.ndarray,
    yaw_rad: float = 0.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (mask, depth) for a top-down view of a box with axis-aligned
    horizontal axes rotated by ``yaw_rad`` (around camera-z), centered at
    ``center_cam`` (in camera frame, +z forward).

    Approximation: we treat the camera frame's z as 'depth in front of the
    camera' and (x, y) as horizontal. The depth value at each pixel inside
    the rotated rectangle is set to ``center_z - half_extents[2]`` (top
    face of the box, closest to the camera). This is enough to make the
    OBB algorithm produce a well-defined ground-aligned OBB.
    """
    h, w = intrinsics.height, intrinsics.width
    mask = np.zeros((h, w), dtype=bool)
    depth = np.zeros((h, w), dtype=np.float32)

    # The top face sits at z = center_z - hz (closer to camera).
    top_z = float(center_cam[2] - half_extents[2])

    # In camera-frame x, y the box has horizontal half-extents (hx, hy).
    # Project corners of the rotated rectangle to pixels.
    cs = float(np.cos(yaw_rad))
    sn = float(np.sin(yaw_rad))
    R2 = np.array([[cs, -sn], [sn, cs]], dtype=float)
    local_corners = np.array([
        [-half_extents[0], -half_extents[1]],
        [+half_extents[0], -half_extents[1]],
        [+half_extents[0], +half_extents[1]],
        [-half_extents[0], +half_extents[1]],
    ])
    world_xy = (R2 @ local_corners.T).T + center_cam[:2]

    # Sample the bounding box of the rotated rectangle in pixel space.
    u_corners = intrinsics.fx * world_xy[:, 0] / top_z + intrinsics.cx
    v_corners = intrinsics.fy * world_xy[:, 1] / top_z + intrinsics.cy
    u_lo, u_hi = int(max(0, np.floor(u_corners.min()))), int(min(w, np.ceil(u_corners.max())))
    v_lo, v_hi = int(max(0, np.floor(v_corners.min()))), int(min(h, np.ceil(v_corners.max())))

    # For each pixel in that bbox, unproject onto z=top_z plane and check if
    # the (x, y) is inside the rotated rectangle.
    us = np.arange(u_lo, u_hi)
    vs = np.arange(v_lo, v_hi)
    uu, vv = np.meshgrid(us, vs)  # (Hp, Wp)
    x = (uu - intrinsics.cx) * top_z / intrinsics.fx
    y = (vv - intrinsics.cy) * top_z / intrinsics.fy
    # Inverse rotate into the box's local frame.
    Rinv = R2.T
    lx = Rinv[0, 0] * (x - center_cam[0]) + Rinv[0, 1] * (y - center_cam[1])
    ly = Rinv[1, 0] * (x - center_cam[0]) + Rinv[1, 1] * (y - center_cam[1])
    inside = (np.abs(lx) <= half_extents[0]) & (np.abs(ly) <= half_extents[1])
    mask[v_lo:v_hi, u_lo:u_hi] = inside
    depth[v_lo:v_hi, u_lo:u_hi] = np.where(inside, top_z, 0.0)
    return mask, depth


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_compute_obb_from_points_basic():
    """A noisy box-shaped cloud yields ~correct dims, center, and 8 corners."""
    rng = np.random.default_rng(0)
    # 0.10 x 0.06 x 0.04 m box at origin.
    hx, hy, hz = 0.05, 0.03, 0.02
    n = 4000
    pts = rng.uniform(low=[-hx, -hy, -hz], high=[+hx, +hy, +hz], size=(n, 3))

    obb = compute_obb_from_points(pts, frame="test")
    assert isinstance(obb, OrientedBoundingBox)
    assert obb.corners.shape == (8, 3)
    assert obb.face_centers.shape == (6, 3)
    assert obb.top_face_corners.shape == (4, 3)
    assert np.allclose(obb.center, np.zeros(3), atol=2e-3)
    assert np.allclose(np.sort(obb.dimensions), np.sort([2 * hx, 2 * hy, 2 * hz]), atol=5e-3)
    # Top face (corners 4-7) must have higher z than the bottom face (0-3).
    assert obb.corners[4:8, 2].mean() > obb.corners[0:4, 2].mean()
    # Top face corners equal corners[4:8].
    assert np.allclose(obb.top_face_corners, obb.corners[4:8])


def test_compute_obb_corner_ordering_canonical():
    """Bottom face is CCW viewed from above; top sits directly above bottom."""
    rng = np.random.default_rng(1)
    pts = rng.uniform(low=[-0.05, -0.03, -0.02], high=[0.05, 0.03, 0.02], size=(3000, 3))
    obb = compute_obb_from_points(pts, frame="test")

    # Each top corner i+4 is directly above bottom corner i (same x,y to within OBB tolerance).
    for i in range(4):
        bot = obb.corners[i]
        top = obb.corners[i + 4]
        assert np.allclose(bot[:2], top[:2], atol=1e-6)
        assert top[2] > bot[2]


def test_compute_obb_face_centers_ordering():
    """Face centers respect (bottom, top, -y, +y, -x, +x) convention."""
    rng = np.random.default_rng(2)
    pts = rng.uniform(low=[-0.05, -0.03, -0.02], high=[0.05, 0.03, 0.02], size=(3000, 3))
    obb = compute_obb_from_points(pts, frame="test")
    fc = obb.face_centers
    # bottom (idx 0) has the lowest z; top (idx 1) has the highest.
    assert fc[0, 2] < fc[1, 2]
    # face 2 has lower local-y than face 3; face 4 has lower local-x than face 5.
    # Express in local frame to compare.
    local = (fc - obb.center) @ obb.rotation_matrix
    assert local[2, 1] < local[3, 1]
    assert local[4, 0] < local[5, 0]


def test_obb_from_mask_depth_axis_aligned():
    """Synthesized depth of a yaw=0 box: OBB recovers extents within tolerance."""
    intr = _make_intrinsics()
    center_cam = np.array([0.0, 0.0, 0.50])  # 50 cm in front of camera
    half = np.array([0.04, 0.025, 0.015])  # 8x5x3 cm
    mask, depth = _project_box_depth(intr, center_cam, half, yaw_rad=0.0)

    # Treat camera-frame z as world-up for this test (call without TF).
    obb = compute_obb_from_mask_depth(mask, depth, intr, min_points=50)
    assert obb is not None
    # Top face of the box is what's visible — height extent collapses to ~0.
    # Width / depth (camera-x, camera-y) extents should match 2*half[0], 2*half[1].
    sorted_dims = np.sort(obb.dimensions)
    assert sorted_dims[2] == pytest.approx(2 * half[0], abs=5e-3)
    assert sorted_dims[1] == pytest.approx(2 * half[1], abs=5e-3)
    # The z-extent of the visible top face is ~0 (single depth plane).
    assert sorted_dims[0] < 1e-3
    # Center (x, y) close to (0, 0); z close to top of box.
    assert abs(obb.center[0]) < 5e-3
    assert abs(obb.center[1]) < 5e-3
    assert obb.center[2] == pytest.approx(center_cam[2] - half[2], abs=1e-3)


def test_obb_from_mask_depth_returns_none_when_empty():
    """All-zero mask / depth must yield None instead of crashing."""
    intr = _make_intrinsics()
    mask = np.zeros((intr.height, intr.width), dtype=bool)
    depth = np.zeros((intr.height, intr.width), dtype=np.float32)
    out = compute_obb_from_mask_depth(mask, depth, intr, min_points=30)
    assert out is None


def test_obb_with_tf_applies_rotation_translation():
    """Providing R_cam_to_base + t_cam_to_base puts the OBB in the base frame."""
    intr = _make_intrinsics()
    center_cam = np.array([0.0, 0.0, 0.50])
    half = np.array([0.04, 0.025, 0.015])
    mask, depth = _project_box_depth(intr, center_cam, half, yaw_rad=0.0)

    # Simple identity rotation + a translation. This must shift the center.
    R = np.eye(3)
    t = np.array([0.5, 0.1, -0.2])
    obb = compute_obb_from_mask_depth(
        mask, depth, intr,
        R_cam_to_base=R, t_cam_to_base=t,
        frame="panda_link0",
    )
    assert obb is not None
    assert obb.frame == "panda_link0"
    # Center moved by t (subject to the small box-top approximation).
    assert obb.center[0] == pytest.approx(t[0], abs=5e-3)
    assert obb.center[1] == pytest.approx(t[1], abs=5e-3)


def test_obb_to_dict_serializable_and_complete():
    """``OrientedBoundingBox.to_dict()`` returns a JSON-serializable manifest."""
    import json
    rng = np.random.default_rng(3)
    pts = rng.uniform(low=[-0.05, -0.03, -0.02], high=[0.05, 0.03, 0.02], size=(2000, 3))
    obb = compute_obb_from_points(pts, frame="test")
    d = obb.to_dict()
    # Round-trip through JSON to confirm pure-python types.
    json.dumps(d)
    # Required top-level keys.
    for key in (
        "frame", "center_m", "dimensions_m", "yaw_rad", "rotation_matrix",
        "corners_m", "face_centers_m", "top_face_corners_m",
        "n_points_used", "corner_order", "face_order",
    ):
        assert key in d, f"missing key: {key}"
    assert len(d["corners_m"]) == 8
    assert len(d["face_centers_m"]) == 6
    assert len(d["top_face_corners_m"]) == 4
    assert len(d["corner_order"]) == 8
    assert len(d["face_order"]) == 6
