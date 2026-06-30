"""Deterministic stub perception — Mac-safe, fast, no GPU."""

from __future__ import annotations

from typing import List, Optional

import numpy as np
from omegaconf import DictConfig

from .base import BasePerception, DetectedObject, PerceptionResult


class StubPerception(BasePerception):
    """Returns one fake DetectedObject per query at deterministic positions.

    The i-th query is placed at a position cycling through a small grid so
    multiple objects don't collide, and assigned a 3D centroid of
    ``(0.3 + i*0.1, 0.0, 0.5)``. Masks are filled rectangles of size
    ``mask_box_px`` around the 2D centroid.
    """

    def __init__(
        self,
        cfg: Optional[DictConfig] = None,
        image_size: tuple = (480, 640),
        mask_box_px: int = 30,
        base_confidence: float = 0.95,
    ) -> None:
        self.cfg = cfg
        self.image_size = image_size  # (H, W)
        self.mask_box_px = int(mask_box_px)
        self.base_confidence = float(base_confidence)

    @property
    def backend_name(self) -> str:
        return "stub"

    def is_available(self) -> bool:
        return True

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    def _grid_centroid(self, index: int, height: int, width: int) -> tuple:
        """Return a deterministic (u, v) for the i-th detected object."""
        # 3x3 grid centered in the image; wraps for index >= 9.
        col = index % 3
        row = (index // 3) % 3
        cell_w = width // 4
        cell_h = height // 4
        u = (col + 1) * cell_w
        v = (row + 1) * cell_h
        return int(u), int(v)

    def detect(
        self,
        rgb: np.ndarray,
        queries: List[str],
        depth: Optional[np.ndarray] = None,
    ) -> PerceptionResult:
        if not isinstance(rgb, np.ndarray):
            raise TypeError(f"rgb must be np.ndarray, got {type(rgb).__name__}")
        if rgb.ndim != 3 or rgb.shape[2] != 3:
            raise ValueError(f"rgb must be HxWx3, got {rgb.shape}")
        h, w = rgb.shape[:2]
        half = self.mask_box_px // 2

        objects: List[DetectedObject] = []
        for i, query in enumerate(queries):
            u, v = self._grid_centroid(i, h, w)
            x1, y1 = max(0, u - half), max(0, v - half)
            x2, y2 = min(w, u + half), min(h, v + half)

            mask = np.zeros((h, w), dtype=bool)
            mask[y1:y2, x1:x2] = True

            centroid_3d = np.array([0.3 + i * 0.1, 0.0, 0.5], dtype=float)

            objects.append(
                DetectedObject(
                    name=str(query),
                    confidence=self.base_confidence - i * 0.01,
                    bbox_2d=(x1, y1, x2, y2),
                    mask=mask,
                    centroid_2d=(u, v),
                    centroid_3d=centroid_3d,
                    extras={"backend": "stub", "index": i},
                )
            )

        return PerceptionResult(objects=objects, annotated_image=None, raw_depth=depth)
