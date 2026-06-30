"""3D oriented bounding box (OBB) from a binary mask + depth image.

Pure NumPy — safe to import on Mac (no ROS, no torch).

Pipeline (per object):

    mask (HxW bool) + depth (HxW, meters or raw) + intrinsics
        -> point cloud in camera frame (N x 3, meters)
        -> optional: transform to base frame
        -> percentile outlier clip
        -> "ground-aligned" OBB:
              z-axis = world up (gravity)
              x, y   = PCA of horizontal coords
        -> 8 corners + face centers + top-face corners + dims + yaw

This module is intentionally decoupled from the runtime pipeline: it
provides a single pure function ``compute_obb_from_mask_depth`` that
can be invoked offline (e.g., the ``scripts/dump_perception_manifest.py``
script) without touching ``pragmabot.pipeline``.

Corner ordering (canonical, always the same)
--------------------------------------------

Indices into ``corners`` (Nx3, world-space, meters):

    Bottom face (z = z_min, CCW viewed from above):
        0: (-x, -y, -z)
        1: (+x, -y, -z)
        2: (+x, +y, -z)
        3: (-x, +y, -z)

    Top face (z = z_max, CCW viewed from above, i above i-4):
        4: (-x, -y, +z)
        5: (+x, -y, +z)
        6: (+x, +y, +z)
        7: (-x, +y, +z)

Where ``+x``/``+y`` are the OBB's local horizontal axes (rotated by
``yaw_rad`` around world Z relative to the world axes).

Face-centers ordering:

    0: bottom (-z), 1: top (+z),
    2: -y side,     3: +y side,
    4: -x side,     5: +x side
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .camera_intrinsics import CameraIntrinsics


# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------


@dataclass
class OrientedBoundingBox:
    """A ground-aligned oriented bounding box.

    All arrays are in the same world frame the caller supplied
    (typically ``panda_link0``). Z is assumed to be up.

    Attributes:
        center: (3,) center of the box [x, y, z], meters.
        dimensions: (3,) extents along OBB-local (x_obb, y_obb, z_obb), meters.
        yaw_rad: rotation around world Z that takes world-x to OBB-local-x.
        rotation_matrix: (3, 3) rotation R such that
            ``world_point = center + R @ local_point``.
        corners: (8, 3) corner points in world frame, in the canonical
            ordering documented at the top of the module.
        face_centers: (6, 3) face centers in world frame, in the canonical
            ordering documented at the top of the module.
        top_face_corners: (4, 3) top-face corners (z = z_max) in CCW order
            viewed from above. Equivalent to ``corners[4:8]``.
        n_points_used: number of point-cloud samples that produced this OBB.
        frame: short identifier of the frame these coordinates live in
            (e.g., ``"camera"`` or ``"panda_link0"``).
    """

    center: np.ndarray
    dimensions: np.ndarray
    yaw_rad: float
    rotation_matrix: np.ndarray
    corners: np.ndarray
    face_centers: np.ndarray
    top_face_corners: np.ndarray
    n_points_used: int
    frame: str = "unknown"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "frame": self.frame,
            "center_m": [float(c) for c in self.center],
            "dimensions_m": [float(d) for d in self.dimensions],
            "yaw_rad": float(self.yaw_rad),
            "rotation_matrix": [[float(v) for v in row] for row in self.rotation_matrix],
            "corners_m": [[float(v) for v in row] for row in self.corners],
            "face_centers_m": [[float(v) for v in row] for row in self.face_centers],
            "top_face_corners_m": [[float(v) for v in row] for row in self.top_face_corners],
            "n_points_used": int(self.n_points_used),
            "corner_order": [
                "bot_-x-y", "bot_+x-y", "bot_+x+y", "bot_-x+y",
                "top_-x-y", "top_+x-y", "top_+x+y", "top_-x+y",
            ],
            "face_order": ["bottom", "top", "-y", "+y", "-x", "+x"],
        }


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _unproject_mask_to_cloud(
    mask: np.ndarray,
    depth: np.ndarray,
    intrinsics: CameraIntrinsics,
) -> np.ndarray:
    """Vectorized back-projection of all masked pixels to 3D (camera frame).

    Returns (N, 3) in meters. Points with invalid / zero depth are dropped.
    """
    if mask is None or depth is None:
        return np.empty((0, 3), dtype=float)
    if mask.shape != depth.shape:
        raise ValueError(
            f"mask shape {mask.shape} != depth shape {depth.shape}"
        )

    ys, xs = np.nonzero(mask)
    if xs.size == 0:
        return np.empty((0, 3), dtype=float)

    raw = depth[ys, xs].astype(np.float64, copy=False)
    finite = np.isfinite(raw)
    raw = raw[finite]
    ys = ys[finite]
    xs = xs[finite]

    z = raw * float(intrinsics.depth_scale)
    valid = z > 0.0
    z = z[valid]
    ys = ys[valid]
    xs = xs[valid]
    if z.size == 0:
        return np.empty((0, 3), dtype=float)

    x = (xs.astype(np.float64) - intrinsics.cx) * z / intrinsics.fx
    y = (ys.astype(np.float64) - intrinsics.cy) * z / intrinsics.fy
    return np.stack([x, y, z], axis=1)


def _percentile_clip(points: np.ndarray, lo: float = 1.0, hi: float = 99.0) -> np.ndarray:
    """Drop points outside ``[lo, hi]`` percentiles on each axis independently."""
    if points.shape[0] < 20:
        return points
    keep = np.ones(points.shape[0], dtype=bool)
    for ax in range(3):
        lo_v, hi_v = np.percentile(points[:, ax], [lo, hi])
        keep &= (points[:, ax] >= lo_v) & (points[:, ax] <= hi_v)
    if keep.sum() < 20:
        return points  # don't over-prune
    return points[keep]


def _transform_points(
    points_cam: np.ndarray,
    R_cam_to_base: Optional[np.ndarray],
    t_cam_to_base: Optional[np.ndarray],
) -> np.ndarray:
    if R_cam_to_base is None or t_cam_to_base is None:
        return points_cam
    R = np.asarray(R_cam_to_base, dtype=float).reshape(3, 3)
    t = np.asarray(t_cam_to_base, dtype=float).reshape(3)
    return points_cam @ R.T + t


def _ground_aligned_obb(points: np.ndarray) -> Tuple[np.ndarray, np.ndarray, float, np.ndarray]:
    """Compute a ground-aligned OBB (z = world up, x/y from horizontal PCA).

    Returns ``(center, dimensions, yaw_rad, rotation_matrix)``.
    """
    if points.shape[0] < 4:
        raise ValueError(
            f"need >= 4 points to build an OBB; got {points.shape[0]}"
        )

    xy = points[:, :2]
    xy_mean = xy.mean(axis=0)
    centered = xy - xy_mean
    # 2x2 covariance; use SVD on centered for numerical stability.
    # For N >= 2 this is well-defined.
    _, _, vt = np.linalg.svd(centered, full_matrices=False)
    # vt rows are principal directions in (x, y); take the largest.
    e1 = vt[0]
    # Ensure right-handed and consistent sign: e1.x >= 0 if possible.
    if e1[0] < 0:
        e1 = -e1
    e2 = np.array([-e1[1], e1[0]])  # 90° CCW; guarantees right-handed when paired with +z

    R = np.eye(3)
    R[:2, 0] = e1
    R[:2, 1] = e2
    # R[:, 2] = [0, 0, 1] (already, from eye init)

    # Project points into the OBB-local frame (translation absorbed into center later).
    local = (points - np.array([xy_mean[0], xy_mean[1], 0.0])) @ R
    lo = local.min(axis=0)
    hi = local.max(axis=0)
    half = 0.5 * (hi - lo)
    local_mid = 0.5 * (hi + lo)

    center_world = np.array([xy_mean[0], xy_mean[1], 0.0]) + R @ local_mid
    dimensions = 2.0 * half  # full extents
    yaw_rad = float(np.arctan2(R[1, 0], R[0, 0]))
    return center_world, dimensions, yaw_rad, R


def _corners_from_box(
    center: np.ndarray, dimensions: np.ndarray, R: np.ndarray
) -> np.ndarray:
    """Generate the 8 corner points in the canonical ordering."""
    hx, hy, hz = 0.5 * dimensions
    # Canonical local-frame corner coordinates (see module docstring).
    local = np.array([
        [-hx, -hy, -hz],
        [+hx, -hy, -hz],
        [+hx, +hy, -hz],
        [-hx, +hy, -hz],
        [-hx, -hy, +hz],
        [+hx, -hy, +hz],
        [+hx, +hy, +hz],
        [-hx, +hy, +hz],
    ])
    return (local @ R.T) + center


def _face_centers_from_box(
    center: np.ndarray, dimensions: np.ndarray, R: np.ndarray
) -> np.ndarray:
    """Centers of the 6 faces in canonical ordering (bottom, top, -y, +y, -x, +x)."""
    hx, hy, hz = 0.5 * dimensions
    local = np.array([
        [0.0, 0.0, -hz],   # bottom
        [0.0, 0.0, +hz],   # top
        [0.0, -hy, 0.0],   # -y
        [0.0, +hy, 0.0],   # +y
        [-hx, 0.0, 0.0],   # -x
        [+hx, 0.0, 0.0],   # +x
    ])
    return (local @ R.T) + center


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_obb_from_points(
    points: np.ndarray,
    frame: str = "unknown",
    percentile_clip: Optional[Tuple[float, float]] = (1.0, 99.0),
) -> OrientedBoundingBox:
    """Build a ground-aligned OBB from an arbitrary (N, 3) point cloud.

    Args:
        points: (N, 3) array of 3D points, meters. Z is assumed up.
        frame: short label for the frame these coordinates live in.
        percentile_clip: low/high percentile cutoff per axis to suppress
            sensor outliers, or ``None`` to disable.
    """
    pts = np.asarray(points, dtype=float).reshape(-1, 3)
    if percentile_clip is not None:
        pts = _percentile_clip(pts, lo=percentile_clip[0], hi=percentile_clip[1])
    center, dims, yaw, R = _ground_aligned_obb(pts)
    corners = _corners_from_box(center, dims, R)
    face_centers = _face_centers_from_box(center, dims, R)
    return OrientedBoundingBox(
        center=center,
        dimensions=dims,
        yaw_rad=yaw,
        rotation_matrix=R,
        corners=corners,
        face_centers=face_centers,
        top_face_corners=corners[4:8].copy(),
        n_points_used=int(pts.shape[0]),
        frame=frame,
    )


def compute_obb_from_mask_depth(
    mask: np.ndarray,
    depth: np.ndarray,
    intrinsics: CameraIntrinsics,
    R_cam_to_base: Optional[np.ndarray] = None,
    t_cam_to_base: Optional[np.ndarray] = None,
    base_offset: Optional[np.ndarray] = None,
    frame: Optional[str] = None,
    percentile_clip: Optional[Tuple[float, float]] = (1.0, 99.0),
    min_points: int = 30,
) -> Optional[OrientedBoundingBox]:
    """Compute a ground-aligned OBB for one masked object.

    If ``R_cam_to_base`` and ``t_cam_to_base`` are provided, the OBB is
    returned in the base frame; otherwise it is returned in the camera
    frame (which still works, just without a gravity-aligned z).

    Args:
        mask: (H, W) boolean mask of the object.
        depth: (H, W) depth image; values multiplied by ``intrinsics.depth_scale``.
        intrinsics: pinhole + depth_scale.
        R_cam_to_base: (3, 3) rotation from camera frame to base frame.
        t_cam_to_base: (3,) translation from camera frame to base frame.
        base_offset: (3,) added to all base-frame coords *after* TF — this is
            the same hand-eye calibration nudge as
            ``robot.perception_offset_base``.
        frame: optional override for the ``frame`` field in the output.
        percentile_clip: low/high percentile cutoff per axis (defense against
            sensor noise), or ``None`` to disable.
        min_points: minimum number of valid 3D points required to build an OBB.

    Returns:
        The :class:`OrientedBoundingBox`, or ``None`` if there aren't enough
        valid 3D points (depth holes, etc.).
    """
    cloud_cam = _unproject_mask_to_cloud(mask, depth, intrinsics)
    if cloud_cam.shape[0] < min_points:
        return None

    if R_cam_to_base is not None and t_cam_to_base is not None:
        cloud = _transform_points(cloud_cam, R_cam_to_base, t_cam_to_base)
        default_frame = "base"
    else:
        cloud = cloud_cam
        default_frame = "camera"

    if base_offset is not None:
        cloud = cloud + np.asarray(base_offset, dtype=float).reshape(3)

    if percentile_clip is not None:
        cloud = _percentile_clip(cloud, lo=percentile_clip[0], hi=percentile_clip[1])
    if cloud.shape[0] < min_points:
        return None

    center, dims, yaw, R = _ground_aligned_obb(cloud)
    corners = _corners_from_box(center, dims, R)
    face_centers = _face_centers_from_box(center, dims, R)
    return OrientedBoundingBox(
        center=center,
        dimensions=dims,
        yaw_rad=yaw,
        rotation_matrix=R,
        corners=corners,
        face_centers=face_centers,
        top_face_corners=corners[4:8].copy(),
        n_points_used=int(cloud.shape[0]),
        frame=frame or default_frame,
    )
