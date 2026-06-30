"""3D axis-aligned bounding box (AABB) from mask + depth.

Pure NumPy — safe to import on Mac (no ROS, no torch).

AABB conventions (always reported in the *frame the points live in*):

    base frame (panda_link0):
        x = robot forward,  y = robot left,  z = world up
            depth_x_m  = extent along base +x (forward / back from robot)
            width_y_m  = extent along base +y (sideways)
            height_z_m = extent along base +z (vertical, gravity-aligned)
            length_m   = max(depth_x_m, width_y_m)   # longest horizontal

    camera frame (camera_color_optical_frame):
        x = image right, y = image down, z = forward (depth from camera)
            extent_x_m = extent in image-right direction
            extent_y_m = extent in image-down direction
            extent_z_m = extent in the depth (forward) direction
            length_m   = max(extent_x_m, extent_y_m)

The base-frame AABB is the one TP-GPT should consume. Camera-frame is
mainly for debugging / visualization.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import numpy as np

from .camera_intrinsics import CameraIntrinsics
from .obb import _percentile_clip, _transform_points, _unproject_mask_to_cloud


@dataclass
class AxisAlignedBoundingBox:
    """3D axis-aligned bounding box in a single frame.

    ``min_xyz`` and ``max_xyz`` are component-wise min/max of the point
    cloud. ``corners`` enumerates the 8 corners in the same canonical
    order as :class:`OrientedBoundingBox`:

        0: (xmin, ymin, zmin)   bottom face
        1: (xmax, ymin, zmin)
        2: (xmax, ymax, zmin)
        3: (xmin, ymax, zmin)
        4: (xmin, ymin, zmax)   top face
        5: (xmax, ymin, zmax)
        6: (xmax, ymax, zmax)
        7: (xmin, ymax, zmax)

    For the base frame: extents = (depth_x, width_y, height_z).
    """

    center: np.ndarray
    min_xyz: np.ndarray
    max_xyz: np.ndarray
    extents: np.ndarray
    corners: np.ndarray
    top_face_corners: np.ndarray
    n_points_used: int
    frame: str = "unknown"

    # ---- Convenience accessors with semantic names (base-frame oriented) ----

    @property
    def depth_x_m(self) -> float:
        """Extent along the frame's +x axis (robot forward in base frame)."""
        return float(self.extents[0])

    @property
    def width_y_m(self) -> float:
        """Extent along the frame's +y axis (robot left in base frame)."""
        return float(self.extents[1])

    @property
    def height_z_m(self) -> float:
        """Extent along the frame's +z axis (world up in base frame)."""
        return float(self.extents[2])

    @property
    def length_horiz_m(self) -> float:
        """Longest horizontal extent: max(depth_x, width_y)."""
        return float(max(self.depth_x_m, self.width_y_m))

    @property
    def width_horiz_m(self) -> float:
        """Shorter horizontal extent: min(depth_x, width_y)."""
        return float(min(self.depth_x_m, self.width_y_m))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "frame": self.frame,
            "center_m": [float(c) for c in self.center],
            "min_xyz_m": [float(c) for c in self.min_xyz],
            "max_xyz_m": [float(c) for c in self.max_xyz],
            "extents_m": [float(c) for c in self.extents],
            "depth_x_m":  self.depth_x_m,
            "width_y_m":  self.width_y_m,
            "height_z_m": self.height_z_m,
            "length_horiz_m": self.length_horiz_m,
            "width_horiz_m":  self.width_horiz_m,
            "corners_m": [[float(v) for v in row] for row in self.corners],
            "top_face_corners_m": [[float(v) for v in row] for row in self.top_face_corners],
            "n_points_used": int(self.n_points_used),
            "corner_order": [
                "(xmin,ymin,zmin)", "(xmax,ymin,zmin)",
                "(xmax,ymax,zmin)", "(xmin,ymax,zmin)",
                "(xmin,ymin,zmax)", "(xmax,ymin,zmax)",
                "(xmax,ymax,zmax)", "(xmin,ymax,zmax)",
            ],
        }


def _corners_from_extents(min_xyz: np.ndarray, max_xyz: np.ndarray) -> np.ndarray:
    xmin, ymin, zmin = min_xyz
    xmax, ymax, zmax = max_xyz
    return np.array([
        [xmin, ymin, zmin],
        [xmax, ymin, zmin],
        [xmax, ymax, zmin],
        [xmin, ymax, zmin],
        [xmin, ymin, zmax],
        [xmax, ymin, zmax],
        [xmax, ymax, zmax],
        [xmin, ymax, zmax],
    ], dtype=float)


def compute_aabb_from_points(
    points: np.ndarray,
    frame: str = "unknown",
    percentile_clip: Optional[Tuple[float, float]] = (1.0, 99.0),
) -> AxisAlignedBoundingBox:
    """Build an AABB from an (N, 3) point cloud."""
    pts = np.asarray(points, dtype=float).reshape(-1, 3)
    if pts.shape[0] < 2:
        raise ValueError(f"need >= 2 points to build an AABB; got {pts.shape[0]}")
    if percentile_clip is not None:
        pts = _percentile_clip(pts, lo=percentile_clip[0], hi=percentile_clip[1])
    min_xyz = pts.min(axis=0)
    max_xyz = pts.max(axis=0)
    extents = max_xyz - min_xyz
    center = 0.5 * (min_xyz + max_xyz)
    corners = _corners_from_extents(min_xyz, max_xyz)
    return AxisAlignedBoundingBox(
        center=center,
        min_xyz=min_xyz,
        max_xyz=max_xyz,
        extents=extents,
        corners=corners,
        top_face_corners=corners[4:8].copy(),
        n_points_used=int(pts.shape[0]),
        frame=frame,
    )


def compute_aabb_from_mask_depth(
    mask: np.ndarray,
    depth: np.ndarray,
    intrinsics: CameraIntrinsics,
    R_cam_to_base: Optional[np.ndarray] = None,
    t_cam_to_base: Optional[np.ndarray] = None,
    base_offset: Optional[np.ndarray] = None,
    frame: Optional[str] = None,
    percentile_clip: Optional[Tuple[float, float]] = (1.0, 99.0),
    min_points: int = 30,
) -> Optional[AxisAlignedBoundingBox]:
    """Compute an AABB for one masked object.

    If a TF (R, t) is supplied, the AABB is in the base frame (axis-aligned
    with base axes), otherwise it's in the camera frame.

    Returns ``None`` if there aren't enough valid 3D points.
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

    return compute_aabb_from_points(
        cloud, frame=frame or default_frame, percentile_clip=None,
    )
