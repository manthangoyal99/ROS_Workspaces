"""Object-class-aware 3D primitive fitting from a cleaned point cloud.

For tabletop objects, a class-specific primitive is *much* tighter than a
generic OBB / AABB because we can encode the prior shape:

    - apple, orange, ball, tomato, lemon, lime  -> ``Sphere``
    - plate, bowl, saucer, disc                  -> ``FlatDisk`` (z-aligned cylinder
                                                    with small height)
    - mug, cup, can, bottle, jar, glass          -> ``UprightCylinder``
    - box, book, brick, cuboid                   -> None (fall back to OBB)

All fitters run RANSAC on the input cloud. Sphere works in any frame;
``FlatDisk`` and ``UprightCylinder`` assume +z is world up, so they should
only be called on points already transformed to base.

Pure NumPy. Deterministic given a seed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


# ---------------------------------------------------------------------------
# Class -> primitive map
# ---------------------------------------------------------------------------


_SPHERE_KEYWORDS = (
    "apple", "orange", "ball", "tomato", "lemon", "lime",
    "onion", "potato", "peach", "plum", "egg",
)
_FLAT_DISK_KEYWORDS = (
    "plate", "bowl", "saucer", "disc", "disk",
)
_UPRIGHT_CYL_KEYWORDS = (
    "mug", "cup", "can", "bottle", "jar", "glass", "tumbler",
)
_OBB_KEYWORDS = (
    "box", "book", "brick", "cuboid", "block",
)


def class_to_primitive(name: str) -> Optional[str]:
    """Return ``'sphere'`` | ``'flat_disk'`` | ``'upright_cylinder'`` | ``None``.

    ``None`` means "no specific primitive — caller should fall back to OBB."
    Matching is case-insensitive substring (DINO often returns multi-word
    names like 'red apple', 'small plate').
    """
    if not name:
        return None
    needle = name.strip().lower()
    for kw in _SPHERE_KEYWORDS:
        if kw in needle:
            return "sphere"
    for kw in _FLAT_DISK_KEYWORDS:
        if kw in needle:
            return "flat_disk"
    for kw in _UPRIGHT_CYL_KEYWORDS:
        if kw in needle:
            return "upright_cylinder"
    for kw in _OBB_KEYWORDS:
        if kw in needle:
            return None
    return None


# ---------------------------------------------------------------------------
# Sphere
# ---------------------------------------------------------------------------


@dataclass
class FittedSphere:
    center: np.ndarray  # (3,)
    radius: float
    n_inliers: int
    inlier_ratio: float
    rmse_m: float
    frame: str = "unknown"

    @property
    def diameter_m(self) -> float:
        return 2.0 * self.radius

    def bbox_corners(self) -> np.ndarray:
        """8 AABB corners of the bounding cube of the sphere."""
        c = self.center
        r = self.radius
        lo = c - r
        hi = c + r
        return np.array([
            [lo[0], lo[1], lo[2]], [hi[0], lo[1], lo[2]],
            [hi[0], hi[1], lo[2]], [lo[0], hi[1], lo[2]],
            [lo[0], lo[1], hi[2]], [hi[0], lo[1], hi[2]],
            [hi[0], hi[1], hi[2]], [lo[0], hi[1], hi[2]],
        ], dtype=float)

    def wireframe_points(self, n: int = 36) -> List[np.ndarray]:
        """Three great circles for visualisation (xy, xz, yz planes)."""
        t = np.linspace(0.0, 2.0 * np.pi, n)
        c = self.center; r = self.radius
        xy = np.stack([c[0] + r * np.cos(t), c[1] + r * np.sin(t),
                       np.full_like(t, c[2])], axis=1)
        xz = np.stack([c[0] + r * np.cos(t), np.full_like(t, c[1]),
                       c[2] + r * np.sin(t)], axis=1)
        yz = np.stack([np.full_like(t, c[0]), c[1] + r * np.cos(t),
                       c[2] + r * np.sin(t)], axis=1)
        return [xy, xz, yz]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "sphere",
            "frame": self.frame,
            "center_m": [float(v) for v in self.center],
            "radius_m": float(self.radius),
            "diameter_m": float(self.diameter_m),
            "n_inliers": int(self.n_inliers),
            "inlier_ratio": float(self.inlier_ratio),
            "rmse_m": float(self.rmse_m),
        }


def _fit_sphere_lsq(points: np.ndarray) -> Tuple[np.ndarray, float]:
    """Algebraic linear least-squares sphere fit from N>=4 points."""
    P = np.asarray(points, dtype=float).reshape(-1, 3)
    A = np.column_stack([2.0 * P, np.ones(P.shape[0])])
    b = (P ** 2).sum(axis=1)
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    center = sol[:3]
    val = float(sol[3] + (center ** 2).sum())
    if val < 0:
        # Numerically degenerate — bail with a tiny radius.
        return center, 0.0
    return center, float(np.sqrt(val))


def fit_sphere_ransac(
    points: np.ndarray,
    *,
    n_iter: int = 300,
    threshold_m: float = 0.005,
    min_radius_m: float = 0.01,
    max_radius_m: float = 0.20,
    rng_seed: int = 0,
    frame: str = "unknown",
) -> Optional[FittedSphere]:
    """RANSAC sphere fit. Returns None if no sensible model found."""
    pts = np.asarray(points, dtype=float).reshape(-1, 3)
    n = pts.shape[0]
    if n < 6:
        return None
    rng = np.random.default_rng(int(rng_seed))
    best_inliers = -1
    best_model: Optional[Tuple[np.ndarray, float, np.ndarray]] = None
    for _ in range(int(n_iter)):
        idx = rng.choice(n, size=4, replace=False)
        c, r = _fit_sphere_lsq(pts[idx])
        if r < min_radius_m or r > max_radius_m or not np.isfinite(r):
            continue
        d = np.abs(np.linalg.norm(pts - c, axis=1) - r)
        inlier_mask = d < float(threshold_m)
        n_in = int(inlier_mask.sum())
        if n_in > best_inliers:
            best_inliers = n_in
            best_model = (c, r, inlier_mask)
    if best_model is None:
        return None

    # Refit on inliers (linear LSQ over the whole inlier set).
    _, _, inlier_mask = best_model
    if int(inlier_mask.sum()) < 4:
        return None
    c, r = _fit_sphere_lsq(pts[inlier_mask])
    if r < min_radius_m or r > max_radius_m or not np.isfinite(r):
        return None
    residuals = np.linalg.norm(pts[inlier_mask] - c, axis=1) - r
    rmse = float(np.sqrt((residuals ** 2).mean()))
    return FittedSphere(
        center=c,
        radius=float(r),
        n_inliers=int(inlier_mask.sum()),
        inlier_ratio=float(inlier_mask.sum()) / n,
        rmse_m=rmse,
        frame=frame,
    )


# ---------------------------------------------------------------------------
# Upright cylinder (mug / cup / can / bottle)
# ---------------------------------------------------------------------------


@dataclass
class FittedUprightCylinder:
    """A z-aligned cylinder. Axis passes through ``(axis_xy[0], axis_xy[1], *)``."""

    axis_xy: np.ndarray  # (2,) — (x, y) of vertical axis in world frame
    z_bottom: float
    z_top: float
    radius: float
    n_inliers: int
    inlier_ratio: float
    rmse_m: float
    frame: str = "unknown"

    @property
    def height_m(self) -> float:
        return float(self.z_top - self.z_bottom)

    @property
    def center(self) -> np.ndarray:
        return np.array([self.axis_xy[0], self.axis_xy[1],
                          0.5 * (self.z_top + self.z_bottom)], dtype=float)

    def bbox_corners(self) -> np.ndarray:
        cx, cy = self.axis_xy
        r = self.radius
        zb, zt = self.z_bottom, self.z_top
        return np.array([
            [cx - r, cy - r, zb], [cx + r, cy - r, zb],
            [cx + r, cy + r, zb], [cx - r, cy + r, zb],
            [cx - r, cy - r, zt], [cx + r, cy - r, zt],
            [cx + r, cy + r, zt], [cx - r, cy + r, zt],
        ], dtype=float)

    def wireframe_points(self, n: int = 36) -> List[np.ndarray]:
        t = np.linspace(0.0, 2.0 * np.pi, n)
        cx, cy = self.axis_xy
        r = self.radius
        bot = np.stack([cx + r * np.cos(t), cy + r * np.sin(t),
                        np.full_like(t, self.z_bottom)], axis=1)
        top = np.stack([cx + r * np.cos(t), cy + r * np.sin(t),
                        np.full_like(t, self.z_top)], axis=1)
        # 4 silhouette vertical lines.
        sides = []
        for theta in (0.0, np.pi / 2, np.pi, 3 * np.pi / 2):
            x = cx + r * np.cos(theta); y = cy + r * np.sin(theta)
            sides.append(np.array([
                [x, y, self.z_bottom], [x, y, self.z_top],
            ]))
        return [bot, top, *sides]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "upright_cylinder",
            "frame": self.frame,
            "axis_xy_m": [float(v) for v in self.axis_xy],
            "z_bottom_m": float(self.z_bottom),
            "z_top_m": float(self.z_top),
            "height_m": float(self.height_m),
            "radius_m": float(self.radius),
            "diameter_m": float(2.0 * self.radius),
            "center_m": [float(v) for v in self.center],
            "n_inliers": int(self.n_inliers),
            "inlier_ratio": float(self.inlier_ratio),
            "rmse_m": float(self.rmse_m),
        }


def _circle_from_3_points(p1, p2, p3) -> Optional[Tuple[float, float, float]]:
    """Exact 2D circle fit from 3 points. Returns (cx, cy, r) or None."""
    ax, ay = p1; bx, by = p2; cx, cy = p3
    d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-9:
        return None
    ux = ((ax ** 2 + ay ** 2) * (by - cy)
          + (bx ** 2 + by ** 2) * (cy - ay)
          + (cx ** 2 + cy ** 2) * (ay - by)) / d
    uy = ((ax ** 2 + ay ** 2) * (cx - bx)
          + (bx ** 2 + by ** 2) * (ax - cx)
          + (cx ** 2 + cy ** 2) * (bx - ax)) / d
    r = float(np.sqrt((ax - ux) ** 2 + (ay - uy) ** 2))
    return float(ux), float(uy), r


def _fit_circle_lsq_2d(points_xy: np.ndarray) -> Tuple[float, float, float]:
    """Algebraic LSQ circle fit. Returns (cx, cy, r)."""
    P = np.asarray(points_xy, dtype=float).reshape(-1, 2)
    A = np.column_stack([2.0 * P, np.ones(P.shape[0])])
    b = (P ** 2).sum(axis=1)
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    cx, cy = sol[0], sol[1]
    val = float(sol[2] + cx ** 2 + cy ** 2)
    r = float(np.sqrt(max(val, 0.0)))
    return float(cx), float(cy), r


def _angular_outer_hull_xy(xy: np.ndarray, n_bins: int = 48) -> np.ndarray:
    """Return the farthest point in each angular bin around the centroid.

    Robust approximation of the (x, y) outer boundary — works whether the
    input cloud is a thin rim (mug, cylinder side wall) or a filled disk
    (plate, top surface seen from above). Falls back to the input if the
    cloud is too small to bin meaningfully.
    """
    pts = np.asarray(xy, dtype=float).reshape(-1, 2)
    n = pts.shape[0]
    if n < n_bins:
        return pts
    centroid = pts.mean(axis=0)
    rel = pts - centroid
    r = np.linalg.norm(rel, axis=1)
    theta = np.arctan2(rel[:, 1], rel[:, 0]) + np.pi  # [0, 2pi)
    bin_idx = np.floor(theta / (2.0 * np.pi) * n_bins).astype(int) % n_bins
    out = []
    for b in range(n_bins):
        sel = bin_idx == b
        if not sel.any():
            continue
        # Index of furthest point in this bin.
        local_idx = np.argmax(np.where(sel, r, -np.inf))
        out.append(pts[local_idx])
    return np.asarray(out, dtype=float)


def fit_upright_cylinder_ransac(
    points: np.ndarray,
    *,
    n_iter: int = 300,
    threshold_m: float = 0.005,
    min_radius_m: float = 0.01,
    max_radius_m: float = 0.20,
    rng_seed: int = 0,
    frame: str = "unknown",
    use_outer_hull: bool = True,
) -> Optional[FittedUprightCylinder]:
    """RANSAC fit of a z-axis-aligned cylinder.

    Assumes +z is world up (base frame). The fit operates on the angular
    outer hull of the horizontal projection so it works equally well for:
        - thin rims (cylinder side wall seen from the side)
        - filled top surfaces (plate / mug top seen from above)
    """
    pts_full = np.asarray(points, dtype=float).reshape(-1, 3)
    n_full = pts_full.shape[0]
    if n_full < 6:
        return None
    xy_full = pts_full[:, :2]
    if use_outer_hull:
        hull = _angular_outer_hull_xy(xy_full)
    else:
        hull = xy_full
    n_hull = hull.shape[0]
    if n_hull < 4:
        return None
    rng = np.random.default_rng(int(rng_seed))
    best_inliers = -1
    best_model: Optional[Tuple[float, float, float, np.ndarray]] = None
    for _ in range(int(n_iter)):
        idx = rng.choice(n_hull, size=3, replace=False)
        sol = _circle_from_3_points(hull[idx[0]], hull[idx[1]], hull[idx[2]])
        if sol is None:
            continue
        cx, cy, r = sol
        if r < min_radius_m or r > max_radius_m:
            continue
        dist = np.abs(np.linalg.norm(hull - np.array([cx, cy]), axis=1) - r)
        inlier_mask = dist < float(threshold_m)
        n_in = int(inlier_mask.sum())
        if n_in > best_inliers:
            best_inliers = n_in
            best_model = (cx, cy, r, inlier_mask)
    if best_model is None:
        return None

    _, _, _, inlier_mask = best_model
    if int(inlier_mask.sum()) < 4:
        return None
    cx, cy, r = _fit_circle_lsq_2d(hull[inlier_mask])
    if r < min_radius_m or r > max_radius_m:
        return None
    # For z extents, use the FULL cloud filtered by horizontal distance,
    # not just hull points (so we recover the true top/bottom heights).
    horiz_dist = np.linalg.norm(xy_full - np.array([cx, cy]), axis=1)
    z_in_mask = horiz_dist < (r + float(threshold_m) * 2.0)
    z_in = pts_full[z_in_mask, 2]
    if z_in.size == 0:
        z_in = pts_full[:, 2]
    residuals = np.linalg.norm(hull[inlier_mask] - np.array([cx, cy]), axis=1) - r
    rmse = float(np.sqrt((residuals ** 2).mean()))
    return FittedUprightCylinder(
        axis_xy=np.array([cx, cy], dtype=float),
        z_bottom=float(z_in.min()),
        z_top=float(z_in.max()),
        radius=float(r),
        n_inliers=int(inlier_mask.sum()),
        inlier_ratio=float(inlier_mask.sum()) / n_hull,
        rmse_m=rmse,
        frame=frame,
    )


# ---------------------------------------------------------------------------
# Flat disk (plate / bowl)
# ---------------------------------------------------------------------------


@dataclass
class FittedFlatDisk:
    """Thin z-aligned cylinder — same shape, semantically a disk."""

    center_xy: np.ndarray
    z_bottom: float
    z_top: float
    radius: float
    n_inliers: int
    inlier_ratio: float
    rmse_m: float
    frame: str = "unknown"

    @property
    def thickness_m(self) -> float:
        return float(self.z_top - self.z_bottom)

    @property
    def center(self) -> np.ndarray:
        return np.array([self.center_xy[0], self.center_xy[1],
                          0.5 * (self.z_top + self.z_bottom)], dtype=float)

    def bbox_corners(self) -> np.ndarray:
        cx, cy = self.center_xy
        r = self.radius
        zb, zt = self.z_bottom, self.z_top
        return np.array([
            [cx - r, cy - r, zb], [cx + r, cy - r, zb],
            [cx + r, cy + r, zb], [cx - r, cy + r, zb],
            [cx - r, cy - r, zt], [cx + r, cy - r, zt],
            [cx + r, cy + r, zt], [cx - r, cy + r, zt],
        ], dtype=float)

    def wireframe_points(self, n: int = 36) -> List[np.ndarray]:
        t = np.linspace(0.0, 2.0 * np.pi, n)
        cx, cy = self.center_xy
        r = self.radius
        return [
            np.stack([cx + r * np.cos(t), cy + r * np.sin(t),
                      np.full_like(t, self.z_top)], axis=1),
            np.stack([cx + r * np.cos(t), cy + r * np.sin(t),
                      np.full_like(t, self.z_bottom)], axis=1),
        ]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "flat_disk",
            "frame": self.frame,
            "center_xy_m": [float(v) for v in self.center_xy],
            "z_bottom_m": float(self.z_bottom),
            "z_top_m": float(self.z_top),
            "thickness_m": float(self.thickness_m),
            "radius_m": float(self.radius),
            "diameter_m": float(2.0 * self.radius),
            "center_m": [float(v) for v in self.center],
            "n_inliers": int(self.n_inliers),
            "inlier_ratio": float(self.inlier_ratio),
            "rmse_m": float(self.rmse_m),
        }


def fit_flat_disk_ransac(
    points: np.ndarray,
    *,
    n_iter: int = 300,
    threshold_m: float = 0.005,
    min_radius_m: float = 0.03,
    max_radius_m: float = 0.30,
    rng_seed: int = 0,
    frame: str = "unknown",
) -> Optional[FittedFlatDisk]:
    """Fit a thin z-axis-aligned disk (plate / bowl).

    Internally the same as :func:`fit_upright_cylinder_ransac` but with
    plate-sized radius bounds and a slightly different label.
    """
    cyl = fit_upright_cylinder_ransac(
        points,
        n_iter=n_iter,
        threshold_m=threshold_m,
        min_radius_m=min_radius_m,
        max_radius_m=max_radius_m,
        rng_seed=rng_seed,
        frame=frame,
    )
    if cyl is None:
        return None
    return FittedFlatDisk(
        center_xy=cyl.axis_xy,
        z_bottom=cyl.z_bottom,
        z_top=cyl.z_top,
        radius=cyl.radius,
        n_inliers=cyl.n_inliers,
        inlier_ratio=cyl.inlier_ratio,
        rmse_m=cyl.rmse_m,
        frame=frame,
    )


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


def auto_fit_primitive(
    points: np.ndarray,
    class_name: str,
    *,
    frame: str = "unknown",
    rng_seed: int = 0,
) -> Optional[Any]:
    """Pick the right fitter for ``class_name`` and run it.

    Returns the fitted primitive (one of the dataclasses) or ``None`` if the
    class has no primitive or the fit failed. Caller should fall back to
    OBB/AABB on ``None``.
    """
    kind = class_to_primitive(class_name)
    if kind is None:
        return None
    if kind == "sphere":
        return fit_sphere_ransac(points, frame=frame, rng_seed=rng_seed)
    if kind == "upright_cylinder":
        return fit_upright_cylinder_ransac(points, frame=frame, rng_seed=rng_seed)
    if kind == "flat_disk":
        return fit_flat_disk_ransac(points, frame=frame, rng_seed=rng_seed)
    return None
