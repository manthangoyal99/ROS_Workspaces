"""Abstract perception interface and result dataclasses."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


@dataclass
class DetectedObject:
    """One detected (and optionally segmented + localized) object."""

    name: str
    confidence: float
    bbox_2d: Tuple[int, int, int, int]  # (x1, y1, x2, y2)
    mask: Optional[np.ndarray]  # HxW bool
    centroid_2d: Tuple[int, int]  # (u, v) in pixels
    centroid_3d: Optional[np.ndarray]  # (x, y, z) in meters, camera frame
    extras: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "confidence": float(self.confidence),
            "bbox_2d": list(self.bbox_2d),
            "centroid_2d": list(self.centroid_2d),
            "centroid_3d": (
                None if self.centroid_3d is None else [float(c) for c in self.centroid_3d]
            ),
            "has_mask": self.mask is not None,
            "extras": dict(self.extras),
        }


@dataclass
class PerceptionResult:
    """Aggregate output of one perception call."""

    objects: List[DetectedObject] = field(default_factory=list)
    annotated_image: Optional[np.ndarray] = None
    raw_depth: Optional[np.ndarray] = None

    def get_object(self, name: str) -> Optional[DetectedObject]:
        """Return the first detected object matching ``name`` (case-insensitive).

        Matches in three passes for robustness against VLMs producing
        slight name variations ("white plate", "the apple", etc.):
          1. Exact match.
          2. Substring match (needle in obj.name).
          3. Reverse substring (obj.name in needle).
        """
        if not name:
            return None
        needle = name.strip().lower()
        for obj in self.objects:
            if obj.name.lower() == needle:
                return obj
        for obj in self.objects:
            if needle in obj.name.lower():
                return obj
        for obj in self.objects:
            if obj.name.lower() in needle:
                return obj
        return None

    def get_all(self, name: str) -> List[DetectedObject]:
        """Return all detected objects matching ``name`` (case-insensitive substring)."""
        if not name:
            return []
        needle = name.strip().lower()
        return [
            obj for obj in self.objects
            if obj.name.lower() == needle or needle in obj.name.lower() or obj.name.lower() in needle
        ]


class BasePerception(ABC):
    """Abstract perception backend."""

    @abstractmethod
    def detect(
        self,
        rgb: np.ndarray,
        queries: List[str],
        depth: Optional[np.ndarray] = None,
    ) -> PerceptionResult:
        """Detect (and segment) objects in ``rgb`` matching the text queries."""

    @abstractmethod
    def is_available(self) -> bool:
        """True if the backend's runtime dependencies are satisfied."""

    @property
    @abstractmethod
    def backend_name(self) -> str:
        """Short identifier of the backend."""
