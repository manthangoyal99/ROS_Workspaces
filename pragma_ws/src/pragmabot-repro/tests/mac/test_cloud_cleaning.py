"""Mac tests for the point-cloud cleaning pipeline."""

from __future__ import annotations

import numpy as np
import pytest

from pragmabot.perception import (
    CameraIntrinsics,
    clean_object_cloud,
    erode_mask,
    fit_table_plane_ransac,
    remove_statistical_outliers,
)


def _intr() -> CameraIntrinsics:
    return CameraIntrinsics(fx=600.0, fy=600.0, cx=320.0, cy=240.0,
                             width=640, height=480, depth_scale=1.0)


# ---------------------------------------------------------------------------
# Erosion
# ---------------------------------------------------------------------------


def test_erode_mask_shrinks_region():
    mask = np.zeros((20, 20), dtype=bool)
    mask[5:15, 5:15] = True  # 10x10 square -> 100 px
    e1 = erode_mask(mask, 1)
    e2 = erode_mask(mask, 2)
    assert int(e1.sum()) == 8 * 8
    assert int(e2.sum()) == 6 * 6
    assert int(erode_mask(mask, 0).sum()) == 100


def test_erode_mask_handles_empty():
    mask = np.zeros((10, 10), dtype=bool)
    assert int(erode_mask(mask, 3).sum()) == 0


# ---------------------------------------------------------------------------
# Statistical outlier removal
# ---------------------------------------------------------------------------


def test_statistical_outlier_removal_drops_outliers():
    rng = np.random.default_rng(0)
    inliers = rng.normal(loc=0.0, scale=0.001, size=(500, 3))
    outliers = np.array([[0.5, 0.5, 0.5], [-0.5, 0.5, 0.5],
                          [0.5, -0.5, 0.5], [0.5, 0.5, -0.5]])
    pts = np.vstack([inliers, outliers])
    cleaned, kept = remove_statistical_outliers(pts, k=10, std_ratio=1.0)
    # Outliers must be dropped; tight inliers should mostly survive.
    assert kept[500:].sum() == 0
    assert kept[:500].sum() >= 480


# ---------------------------------------------------------------------------
# clean_object_cloud
# ---------------------------------------------------------------------------


def test_clean_object_cloud_removes_depth_jump_bleed():
    """Apple-on-table simulation: mask covers apple + 2px of table behind it."""
    intr = _intr()
    h, w = intr.height, intr.width
    mask = np.zeros((h, w), dtype=bool)
    depth = np.zeros((h, w), dtype=np.float32)

    # 50x50 px "apple" patch at depth 0.95m.
    apple_box = (215, 295, 265, 345)
    mask[apple_box[1]:apple_box[3], apple_box[0]:apple_box[2]] = True
    depth[apple_box[1]:apple_box[3], apple_box[0]:apple_box[2]] = 0.95

    # Mask leak: mark a frame 2px wide around the apple as belonging to mask
    # but the depth at those pixels is 1.05m (table behind).
    leak = 2
    big_box = (apple_box[0] - leak, apple_box[1] - leak,
               apple_box[2] + leak, apple_box[3] + leak)
    leak_mask = np.zeros((h, w), dtype=bool)
    leak_mask[big_box[1]:big_box[3], big_box[0]:big_box[2]] = True
    leak_mask[apple_box[1]:apple_box[3], apple_box[0]:apple_box[2]] = False
    mask |= leak_mask
    depth[leak_mask] = 1.05  # 10cm behind

    # Disable erosion so the depth-jump filter must do the work on its own.
    points, mask_used, report = clean_object_cloud(
        mask, depth, intr, erosion_px=0, depth_jump_threshold_m=0.03,
    )
    assert points.shape[0] > 100
    # All cleaned points should be at z ~0.95 (apple), not 1.05 (table).
    z_vals = points[:, 2]
    assert z_vals.max() < 0.97
    assert z_vals.min() > 0.94
    # The depth-jump filter trimmed the leak pixels off the valid set.
    assert report.n_pixels_with_valid_depth > report.n_pixels_after_depth_jump
    assert report.mask_median_depth_m == pytest.approx(0.95, abs=1e-2)


def test_clean_object_cloud_empty_mask():
    intr = _intr()
    mask = np.zeros((intr.height, intr.width), dtype=bool)
    depth = np.zeros((intr.height, intr.width), dtype=np.float32)
    pts, _, report = clean_object_cloud(mask, depth, intr)
    assert pts.shape == (0, 3)
    assert report.n_pixels_after_depth_jump == 0


# ---------------------------------------------------------------------------
# Table plane RANSAC
# ---------------------------------------------------------------------------


def test_fit_table_plane_recovers_horizontal_plane():
    """Cloud of a horizontal plane at z=0 plus 5% random clutter."""
    rng = np.random.default_rng(0)
    n_plane = 800
    plane_pts = np.column_stack([
        rng.uniform(-0.3, 0.3, n_plane),
        rng.uniform(-0.3, 0.3, n_plane),
        rng.normal(0.0, 0.001, n_plane),  # 1 mm noise
    ])
    n_clutter = 40
    clutter = np.column_stack([
        rng.uniform(-0.3, 0.3, n_clutter),
        rng.uniform(-0.3, 0.3, n_clutter),
        rng.uniform(0.05, 0.20, n_clutter),  # objects above the plane
    ])
    cloud = np.vstack([plane_pts, clutter])
    plane = fit_table_plane_ransac(
        cloud, n_iter=200, threshold_m=0.005,
        up_hint=np.array([0.0, 0.0, 1.0]),
    )
    assert plane is not None
    # Normal should be ~+z.
    assert plane.normal[2] > 0.99
    # |d| ~ 0 because the plane is at z=0.
    assert abs(plane.d) < 0.005
    assert plane.n_inliers > 700
