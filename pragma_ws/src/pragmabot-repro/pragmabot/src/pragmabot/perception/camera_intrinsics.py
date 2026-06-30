"""Pinhole camera intrinsics, depth back-projection, and FPS — pure NumPy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
from omegaconf import DictConfig


@dataclass
class CameraIntrinsics:
    """Pinhole intrinsics with a depth scale.

    ``depth_scale`` multiplies the raw depth value to convert it to meters
    (e.g., 0.001 for RealSense uint16 depth in millimeters).
    """

    fx: float
    fy: float
    cx: float
    cy: float
    width: int
    height: int
    depth_scale: float = 1.0

    # ------------------------------------------------------------------
    # Constructors
    # ------------------------------------------------------------------

    @classmethod
    def from_config(cls, cfg: DictConfig) -> "CameraIntrinsics":
        """Build from the top-level config's ``camera`` section."""
        camera = cfg.camera if "camera" in cfg else cfg
        return cls(
            fx=float(camera.fx),
            fy=float(camera.fy),
            cx=float(camera.cx),
            cy=float(camera.cy),
            width=int(camera.width),
            height=int(camera.height),
            depth_scale=float(camera.get("depth_scale", 1.0)),
        )

    @classmethod
    def from_ros_camera_info(cls, msg) -> "CameraIntrinsics":
        """Build from a ``sensor_msgs/CameraInfo`` message.

        ROS guard: this method only requires the message's *fields* (not rospy
        itself), so no import of rospy here. Callers on Mac should not call
        this method.
        """
        # K is the 3x3 intrinsic matrix flattened in row-major order:
        # [fx 0 cx; 0 fy cy; 0 0 1]
        K = list(getattr(msg, "K", []))
        if len(K) != 9:
            raise ValueError(f"CameraInfo.K has length {len(K)}, expected 9.")
        return cls(
            fx=float(K[0]),
            fy=float(K[4]),
            cx=float(K[2]),
            cy=float(K[5]),
            width=int(getattr(msg, "width", 0)),
            height=int(getattr(msg, "height", 0)),
            depth_scale=1.0,
        )

    # ------------------------------------------------------------------
    # Geometry
    # ------------------------------------------------------------------

    def project(self, point_3d: np.ndarray) -> Optional[np.ndarray]:
        """Project a 3D point in the camera frame to pixel (u, v)."""
        p = np.asarray(point_3d, dtype=float).reshape(-1)
        if p.shape != (3,):
            raise ValueError(f"point_3d must be shape (3,), got {p.shape}")
        z = float(p[2])
        if z <= 0:
            return None
        u = self.fx * p[0] / z + self.cx
        v = self.fy * p[1] / z + self.cy
        return np.array([u, v], dtype=float)


def unproject_pixel(
    u: int,
    v: int,
    depth: np.ndarray,
    intrinsics: CameraIntrinsics,
) -> Optional[np.ndarray]:
    """Back-project pixel (u, v) to a 3D point in the camera frame (meters).

    Returns ``None`` if the depth at that pixel is zero or invalid.
    """
    if depth is None:
        return None
    u_i, v_i = int(u), int(v)
    if not (0 <= u_i < depth.shape[1] and 0 <= v_i < depth.shape[0]):
        return None
    raw = depth[v_i, u_i]
    if not np.isfinite(raw):
        return None
    z = float(raw) * float(intrinsics.depth_scale)
    if z <= 0.0:
        return None
    x = (u_i - intrinsics.cx) * z / intrinsics.fx
    y = (v_i - intrinsics.cy) * z / intrinsics.fy
    return np.array([x, y, z], dtype=float)


def unproject_mask(
    mask: np.ndarray,
    depth: np.ndarray,
    intrinsics: CameraIntrinsics,
    method: str = "centroid",
) -> Optional[np.ndarray]:
    """Unproject a representative point of a binary mask to 3D.

    Methods:
        - ``"centroid"``: use the integer centroid (mean of mask coords).
        - ``"farthest_point"``: FPS over masked pixels (paper §IV.F); the
          first returned point is used (the geometric "extremes" candidate).
    """
    if mask is None or depth is None:
        return None
    ys, xs = np.nonzero(mask)
    if xs.size == 0:
        return None

    if method == "centroid":
        u, v = int(round(xs.mean())), int(round(ys.mean()))
        return unproject_pixel(u, v, depth, intrinsics)

    if method == "farthest_point":
        coords = np.stack([xs, ys], axis=1)  # (N, 2) — (u, v) order
        idx = farthest_point_sample(coords, min(8, coords.shape[0]))
        for i in idx:
            u, v = int(coords[i, 0]), int(coords[i, 1])
            point = unproject_pixel(u, v, depth, intrinsics)
            if point is not None:
                return point
        return None

    raise ValueError(f"unknown method: {method!r}")


def farthest_point_sample(points: np.ndarray, n_samples: int) -> np.ndarray:
    """Farthest-point sampling on 2D pixel coordinates.

    Args:
        points: (N, 2) array of (u, v) pixel coordinates.
        n_samples: number of samples to return.

    Returns:
        (n_samples,) int64 array of indices into ``points``.
    """
    pts = np.asarray(points, dtype=float)
    if pts.ndim != 2 or pts.shape[1] < 2:
        raise ValueError(f"points must be (N, 2), got {pts.shape}")
    n_total = pts.shape[0]
    n = int(min(max(n_samples, 0), n_total))
    if n == 0:
        return np.empty((0,), dtype=np.int64)

    indices = np.empty(n, dtype=np.int64)
    indices[0] = 0  # deterministic start
    dist = np.linalg.norm(pts - pts[0], axis=1)
    for i in range(1, n):
        nxt = int(np.argmax(dist))
        indices[i] = nxt
        new_d = np.linalg.norm(pts - pts[nxt], axis=1)
        dist = np.minimum(dist, new_d)
    return indices
