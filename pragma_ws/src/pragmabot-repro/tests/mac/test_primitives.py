"""Mac tests for the primitive-fitting module."""

from __future__ import annotations

import json

import numpy as np
import pytest

from pragmabot.perception import (
    auto_fit_primitive,
    class_to_primitive,
    fit_flat_disk_ransac,
    fit_sphere_ransac,
    fit_upright_cylinder_ransac,
)


# ---------------------------------------------------------------------------
# Class -> primitive mapping
# ---------------------------------------------------------------------------


def test_class_to_primitive_simple():
    assert class_to_primitive("apple") == "sphere"
    assert class_to_primitive("RED apple") == "sphere"
    assert class_to_primitive("the orange") == "sphere"
    assert class_to_primitive("plate") == "flat_disk"
    assert class_to_primitive("small white plate") == "flat_disk"
    assert class_to_primitive("ceramic mug") == "upright_cylinder"
    assert class_to_primitive("can of soda") == "upright_cylinder"
    assert class_to_primitive("cardboard box") is None
    assert class_to_primitive("") is None
    assert class_to_primitive("unknown widget") is None


# ---------------------------------------------------------------------------
# Sphere RANSAC
# ---------------------------------------------------------------------------


def _hemisphere_cloud(radius: float, center: np.ndarray, n: int, noise_m: float = 0.001):
    """Sample points on a hemisphere (top half, simulating one camera view)."""
    rng = np.random.default_rng(0)
    # Uniform sample on the visible (top) hemisphere via z-aligned cap.
    phi = rng.uniform(0.0, 2 * np.pi, n)
    theta = np.arccos(1 - rng.uniform(0.0, 1.0, n))  # 0..pi/2
    x = radius * np.sin(theta) * np.cos(phi)
    y = radius * np.sin(theta) * np.sin(phi)
    z = radius * np.cos(theta)
    pts = np.column_stack([x, y, z]) + center
    pts += rng.normal(0.0, noise_m, pts.shape)
    return pts


def test_sphere_ransac_recovers_apple():
    """3.5cm-radius hemisphere => RANSAC recovers center & radius."""
    radius = 0.035  # 7cm diameter apple
    center = np.array([0.0, 0.0, 0.0])
    pts = _hemisphere_cloud(radius, center, n=600, noise_m=0.001)
    sphere = fit_sphere_ransac(pts, threshold_m=0.003, n_iter=200, frame="test")
    assert sphere is not None
    assert sphere.radius == pytest.approx(radius, abs=2e-3)
    assert np.allclose(sphere.center, center, atol=2e-3)
    assert sphere.inlier_ratio > 0.85
    assert sphere.diameter_m == pytest.approx(2 * radius, abs=4e-3)
    # Wireframe + bbox sanity.
    assert sphere.bbox_corners().shape == (8, 3)
    assert all(arr.shape == (36, 3) for arr in sphere.wireframe_points())


def test_sphere_to_dict_serializable():
    pts = _hemisphere_cloud(0.035, np.array([0.1, 0.2, 0.3]), n=500)
    sphere = fit_sphere_ransac(pts, frame="panda_link0")
    assert sphere is not None
    d = sphere.to_dict()
    json.dumps(d)
    for k in ("type", "center_m", "radius_m", "diameter_m",
               "n_inliers", "inlier_ratio", "rmse_m", "frame"):
        assert k in d


def test_sphere_ransac_returns_none_for_random_cloud():
    """A uniform 3D random cloud should NOT yield a confident sphere."""
    rng = np.random.default_rng(1)
    pts = rng.uniform(-0.05, 0.05, size=(400, 3))
    sphere = fit_sphere_ransac(pts, threshold_m=0.001, n_iter=200)
    # Either returns None, or returns something with low inlier_ratio.
    if sphere is not None:
        assert sphere.inlier_ratio < 0.7


# ---------------------------------------------------------------------------
# Upright cylinder RANSAC
# ---------------------------------------------------------------------------


def test_upright_cylinder_recovers_mug():
    """4cm-radius x 10cm-tall cylinder."""
    rng = np.random.default_rng(2)
    n = 800
    cx, cy = 0.4, 0.1
    r = 0.04
    z_b, z_t = 0.0, 0.10
    phi = rng.uniform(0.0, 2 * np.pi, n)
    z = rng.uniform(z_b, z_t, n)
    x = cx + r * np.cos(phi); y = cy + r * np.sin(phi)
    pts = np.column_stack([x, y, z]) + rng.normal(0.0, 0.0005, (n, 3))
    cyl = fit_upright_cylinder_ransac(pts, threshold_m=0.003, frame="test")
    assert cyl is not None
    assert cyl.radius == pytest.approx(r, abs=2e-3)
    assert cyl.axis_xy[0] == pytest.approx(cx, abs=2e-3)
    assert cyl.axis_xy[1] == pytest.approx(cy, abs=2e-3)
    assert cyl.z_bottom == pytest.approx(z_b, abs=5e-3)
    assert cyl.z_top == pytest.approx(z_t, abs=5e-3)
    assert cyl.height_m == pytest.approx(z_t - z_b, abs=8e-3)


# ---------------------------------------------------------------------------
# Flat disk RANSAC
# ---------------------------------------------------------------------------


def test_flat_disk_recovers_plate():
    """13cm-radius plate, 2cm thick."""
    rng = np.random.default_rng(3)
    n = 1200
    cx, cy = 0.5, 0.2
    r = 0.13
    z_b, z_t = 0.00, 0.02
    # Sample top + bottom + rim.
    samples = []
    for _ in range(3):
        rho = rng.uniform(0.0, r, n // 3)
        phi = rng.uniform(0.0, 2 * np.pi, n // 3)
        x = cx + rho * np.cos(phi); y = cy + rho * np.sin(phi)
        samples.append(np.column_stack([x, y, rng.uniform(z_b, z_t, n // 3)]))
    pts = np.vstack(samples) + rng.normal(0.0, 0.0005, (3 * (n // 3), 3))
    disk = fit_flat_disk_ransac(pts, threshold_m=0.005, frame="test")
    assert disk is not None
    # Disk fit uses the rim — for a top-down view this gets approximate but
    # within a few mm. Allow generous tolerance.
    assert disk.radius == pytest.approx(r, abs=8e-3)
    assert disk.center_xy[0] == pytest.approx(cx, abs=5e-3)
    assert disk.center_xy[1] == pytest.approx(cy, abs=5e-3)
    assert disk.thickness_m < 0.04


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


def test_auto_fit_primitive_dispatches_correctly():
    apple = _hemisphere_cloud(0.035, np.array([0.0, 0.0, 0.0]), n=500)
    p = auto_fit_primitive(apple, "the red apple", frame="test")
    assert p is not None
    assert p.to_dict()["type"] == "sphere"

    # A box class -> no primitive.
    assert auto_fit_primitive(apple, "cardboard box") is None
    # Unknown class -> no primitive.
    assert auto_fit_primitive(apple, "widget") is None
