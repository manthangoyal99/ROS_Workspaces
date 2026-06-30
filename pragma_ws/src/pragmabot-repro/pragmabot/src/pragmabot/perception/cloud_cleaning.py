"""Clean a masked depth blob into a tight 3D point cloud.

Pure NumPy (+ sklearn.neighbors for kNN, already a base dep). No ROS.

Pipeline:

    mask (HxW bool) + depth (HxW)
        -> erode mask by `erosion_px` (kills 1-2 px SAM edge bleed)
        -> drop pixels with invalid / zero depth
        -> drop pixels whose depth differs from the *mask-median depth*
           by more than `depth_jump_threshold_m` (kills "table behind edge"
           bleed which is the #1 cause of inflated camera-frame z extent)
        -> back-project to 3D (camera frame)
        -> statistical outlier removal (kNN distance threshold)
        -> return cleaned (N, 3) point cloud + a CleaningReport

A separate :func:`fit_table_plane_ransac` fits a dominant plane to the
workspace ROI so callers can snap object z to the table.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional, Tuple

import numpy as np

from .camera_intrinsics import CameraIntrinsics


@dataclass
class CleaningReport:
    """Per-object cleaning telemetry — copied verbatim into the manifest."""

    n_pixels_in_mask: int
    n_pixels_after_erosion: int
    n_pixels_with_valid_depth: int
    n_pixels_after_depth_jump: int
    n_points_after_statistical: int
    mask_median_depth_m: float
    erosion_px: int
    depth_jump_threshold_m: float
    statistical_k: int
    statistical_std_ratio: float

    def to_dict(self) -> Dict[str, Any]:
        return {k: (float(v) if isinstance(v, np.floating) else v)
                for k, v in asdict(self).items()}


# ---------------------------------------------------------------------------
# Erosion (no scipy dep)
# ---------------------------------------------------------------------------


def _erode_one_px(mask: np.ndarray) -> np.ndarray:
    """4-connectivity 1-pixel binary erosion. Pure numpy."""
    if mask.size == 0:
        return mask
    out = mask.copy()
    out[1:] &= mask[:-1]
    out[:-1] &= mask[1:]
    out[:, 1:] &= mask[:, :-1]
    out[:, :-1] &= mask[:, 1:]
    return out


def erode_mask(mask: np.ndarray, px: int) -> np.ndarray:
    """Erode `mask` by `px` pixels (4-connectivity, repeated)."""
    out = np.asarray(mask, dtype=bool)
    for _ in range(max(0, int(px))):
        out = _erode_one_px(out)
    return out


# ---------------------------------------------------------------------------
# Statistical outlier removal (kNN)
# ---------------------------------------------------------------------------


def _knn_mean_dist(pts: np.ndarray, k: int) -> np.ndarray:
    """Mean distance to each point's ``k`` nearest neighbors.

    Uses sklearn when available; otherwise falls back to a pure-numpy O(N^2)
    pairwise distance computation (fast enough up to ~5000 points).
    """
    n = pts.shape[0]
    k_eff = int(min(max(k, 1), n - 1))
    try:
        from sklearn.neighbors import NearestNeighbors  # type: ignore
        nn = NearestNeighbors(n_neighbors=k_eff + 1).fit(pts)
        dists, _ = nn.kneighbors(pts)
        return dists[:, 1:].mean(axis=1)
    except ImportError:
        pass
    # Pure-numpy fallback. Cap size for safety; warn if huge.
    if n > 6000:
        # For very large clouds we'd hit memory pressure; just do a stride.
        stride = max(1, n // 4000)
        sample = pts[::stride]
    else:
        sample = pts
    # ||pts - sample||^2 = ||pts||^2 + ||sample||^2 - 2 pts . sample
    d2 = (
        (pts ** 2).sum(axis=1, keepdims=True)
        + (sample ** 2).sum(axis=1)[None, :]
        - 2.0 * pts @ sample.T
    )
    np.maximum(d2, 0.0, out=d2)
    d = np.sqrt(d2)
    # Drop self-distance: for each row, find the smallest value and zero it.
    # (Works whether or not the row actually contains the point itself.)
    if sample is pts:
        np.fill_diagonal(d, np.inf)
    # Sort and average the k smallest.
    d_part = np.partition(d, kth=k_eff - 1, axis=1)[:, :k_eff]
    return d_part.mean(axis=1)


def remove_statistical_outliers(
    points: np.ndarray, k: int = 10, std_ratio: float = 2.0,
) -> Tuple[np.ndarray, np.ndarray]:
    """Open3D-style statistical outlier removal.

    For each point, compute the mean distance to its ``k`` nearest neighbors.
    Globally, compute ``mean(d) + std_ratio * std(d)``. Drop points whose
    ``mean(d)`` exceeds the global threshold.

    Returns ``(filtered_points, kept_mask)``.
    """
    pts = np.asarray(points, dtype=float).reshape(-1, 3)
    n = pts.shape[0]
    if n < max(k + 1, 8):
        return pts, np.ones(n, dtype=bool)
    mean_dist = _knn_mean_dist(pts, k=k)
    thresh = mean_dist.mean() + float(std_ratio) * mean_dist.std()
    kept = mean_dist < thresh
    return pts[kept], kept


# ---------------------------------------------------------------------------
# Vectorised unprojection
# ---------------------------------------------------------------------------


def _unproject_pixels(
    us: np.ndarray, vs: np.ndarray, z_m: np.ndarray, intr: CameraIntrinsics,
) -> np.ndarray:
    """(N, 3) camera-frame back-projection from pixel + depth (already in m)."""
    x = (us.astype(np.float64) - intr.cx) * z_m / intr.fx
    y = (vs.astype(np.float64) - intr.cy) * z_m / intr.fy
    return np.stack([x, y, z_m], axis=1)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def clean_object_cloud(
    mask: np.ndarray,
    depth: np.ndarray,
    intrinsics: CameraIntrinsics,
    *,
    erosion_px: int = 1,
    depth_jump_threshold_m: float = 0.03,
    statistical_k: int = 10,
    statistical_std_ratio: float = 2.0,
) -> Tuple[np.ndarray, np.ndarray, CleaningReport]:
    """Clean one object's masked depth into a tight 3D point cloud.

    Args:
        mask:  (H, W) bool object mask.
        depth: (H, W) depth image; values multiplied by intrinsics.depth_scale.
        intrinsics: pinhole + depth_scale.
        erosion_px: shrink the mask by this many pixels before unprojecting.
        depth_jump_threshold_m: keep pixels within this distance of the mask
            median depth. Set to a large value (e.g. 10.0) to disable.
        statistical_k: kNN size for statistical outlier removal.
        statistical_std_ratio: drop points whose mean-kNN distance exceeds
            ``mean + std_ratio * std`` of the population.

    Returns:
        ``(points, mask_used, report)``:

        - ``points`` (M, 3) cleaned point cloud in camera frame, meters.
        - ``mask_used`` (H, W) eroded mask used for the unprojection (useful
          for visualisation).
        - ``report`` per-step counts and parameters.
    """
    mask_b = np.asarray(mask, dtype=bool)
    if mask_b.shape != depth.shape:
        raise ValueError(
            f"mask shape {mask_b.shape} != depth shape {depth.shape}"
        )

    n_in_mask = int(mask_b.sum())

    eroded = erode_mask(mask_b, erosion_px)
    n_eroded = int(eroded.sum())

    # Valid depth inside the eroded mask.
    ys, xs = np.nonzero(eroded)
    raw = depth[ys, xs].astype(np.float64, copy=False)
    finite = np.isfinite(raw) & (raw > 0)
    raw = raw[finite]; ys = ys[finite]; xs = xs[finite]
    z_m = raw * float(intrinsics.depth_scale)
    n_valid = int(z_m.size)

    if n_valid == 0:
        empty = np.empty((0, 3), dtype=float)
        report = CleaningReport(
            n_pixels_in_mask=n_in_mask,
            n_pixels_after_erosion=n_eroded,
            n_pixels_with_valid_depth=0,
            n_pixels_after_depth_jump=0,
            n_points_after_statistical=0,
            mask_median_depth_m=0.0,
            erosion_px=int(erosion_px),
            depth_jump_threshold_m=float(depth_jump_threshold_m),
            statistical_k=int(statistical_k),
            statistical_std_ratio=float(statistical_std_ratio),
        )
        return empty, eroded, report

    # Depth-jump filter against the median of the *eroded* mask.
    median_z = float(np.median(z_m))
    keep_jump = np.abs(z_m - median_z) <= float(depth_jump_threshold_m)
    z_m = z_m[keep_jump]; ys = ys[keep_jump]; xs = xs[keep_jump]
    n_jump = int(z_m.size)

    cloud = _unproject_pixels(xs, ys, z_m, intrinsics)

    cloud, _ = remove_statistical_outliers(
        cloud, k=int(statistical_k), std_ratio=float(statistical_std_ratio),
    )
    n_stat = int(cloud.shape[0])

    report = CleaningReport(
        n_pixels_in_mask=n_in_mask,
        n_pixels_after_erosion=n_eroded,
        n_pixels_with_valid_depth=n_valid,
        n_pixels_after_depth_jump=n_jump,
        n_points_after_statistical=n_stat,
        mask_median_depth_m=median_z,
        erosion_px=int(erosion_px),
        depth_jump_threshold_m=float(depth_jump_threshold_m),
        statistical_k=int(statistical_k),
        statistical_std_ratio=float(statistical_std_ratio),
    )
    return cloud, eroded, report


# ---------------------------------------------------------------------------
# Table-plane RANSAC
# ---------------------------------------------------------------------------


@dataclass
class TablePlane:
    """A plane: ``n . x = d`` with unit normal ``n`` (3,)."""

    normal: np.ndarray
    d: float
    n_inliers: int
    inlier_ratio: float

    def height_above(self, points: np.ndarray) -> np.ndarray:
        """Signed distance from each row of ``points`` to the plane along ``n``.

        Positive values are on the side the normal points to (callers should
        ensure the normal points "up" for sensible "height above table").
        """
        pts = np.asarray(points, dtype=float).reshape(-1, 3)
        return pts @ self.normal - self.d

    def to_dict(self) -> Dict[str, Any]:
        return {
            "normal": [float(v) for v in self.normal],
            "d": float(self.d),
            "n_inliers": int(self.n_inliers),
            "inlier_ratio": float(self.inlier_ratio),
        }


def fit_table_plane_ransac(
    points: np.ndarray,
    n_iter: int = 200,
    threshold_m: float = 0.01,
    rng_seed: int = 0,
    up_hint: Optional[np.ndarray] = None,
) -> Optional[TablePlane]:
    """RANSAC a dominant plane from an (N, 3) point cloud.

    If ``up_hint`` is provided, the returned normal is flipped so that
    ``n . up_hint > 0`` — useful when you know which side is "up" (in base
    frame, pass ``np.array([0, 0, 1])``).
    """
    pts = np.asarray(points, dtype=float).reshape(-1, 3)
    n = pts.shape[0]
    if n < 20:
        return None
    rng = np.random.default_rng(int(rng_seed))
    best_inliers = -1
    best_mask: Optional[np.ndarray] = None
    best_plane: Optional[Tuple[np.ndarray, float]] = None
    for _ in range(int(n_iter)):
        idx = rng.choice(n, size=3, replace=False)
        p1, p2, p3 = pts[idx]
        normal = np.cross(p2 - p1, p3 - p1)
        norm = float(np.linalg.norm(normal))
        if norm < 1e-9:
            continue
        normal = normal / norm
        d = float(normal @ p1)
        dist = np.abs(pts @ normal - d)
        inlier_mask = dist < float(threshold_m)
        n_in = int(inlier_mask.sum())
        if n_in > best_inliers:
            best_inliers = n_in
            best_mask = inlier_mask
            best_plane = (normal, d)
    if best_plane is None or best_mask is None:
        return None

    # Refine using SVD on the inliers (Total Least Squares).
    pin = pts[best_mask]
    centroid = pin.mean(axis=0)
    _, _, vt = np.linalg.svd(pin - centroid, full_matrices=False)
    normal = vt[-1]
    d = float(normal @ centroid)
    if up_hint is not None:
        if float(normal @ np.asarray(up_hint, dtype=float)) < 0.0:
            normal = -normal
            d = -d
    n_inliers = int(best_mask.sum())
    return TablePlane(
        normal=normal,
        d=d,
        n_inliers=n_inliers,
        inlier_ratio=n_inliers / n,
    )
