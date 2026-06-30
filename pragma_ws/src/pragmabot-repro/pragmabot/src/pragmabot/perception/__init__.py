"""Perception layer — object detection, segmentation, 3D localization."""

from .annotation import ImageAnnotator
from .base import BasePerception, DetectedObject, PerceptionResult
from .camera_intrinsics import (
    CameraIntrinsics,
    farthest_point_sample,
    unproject_mask,
    unproject_pixel,
)
from .aabb import (
    AxisAlignedBoundingBox,
    compute_aabb_from_mask_depth,
    compute_aabb_from_points,
)
from .cloud_cleaning import (
    CleaningReport,
    TablePlane,
    clean_object_cloud,
    erode_mask,
    fit_table_plane_ransac,
    remove_statistical_outliers,
)
from .factory import get_perception
from .obb import (
    OrientedBoundingBox,
    compute_obb_from_mask_depth,
    compute_obb_from_points,
)
from .primitives import (
    FittedFlatDisk,
    FittedSphere,
    FittedUprightCylinder,
    auto_fit_primitive,
    class_to_primitive,
    fit_flat_disk_ransac,
    fit_sphere_ransac,
    fit_upright_cylinder_ransac,
)
from .stub_perception import StubPerception

__all__ = [
    "BasePerception",
    "DetectedObject",
    "PerceptionResult",
    "StubPerception",
    "CameraIntrinsics",
    "unproject_pixel",
    "unproject_mask",
    "farthest_point_sample",
    "ImageAnnotator",
    "get_perception",
    "OrientedBoundingBox",
    "compute_obb_from_mask_depth",
    "compute_obb_from_points",
    "AxisAlignedBoundingBox",
    "compute_aabb_from_mask_depth",
    "compute_aabb_from_points",
    "CleaningReport",
    "TablePlane",
    "clean_object_cloud",
    "erode_mask",
    "fit_table_plane_ransac",
    "remove_statistical_outliers",
    "FittedFlatDisk",
    "FittedSphere",
    "FittedUprightCylinder",
    "auto_fit_primitive",
    "class_to_primitive",
    "fit_flat_disk_ransac",
    "fit_sphere_ransac",
    "fit_upright_cylinder_ransac",
]
