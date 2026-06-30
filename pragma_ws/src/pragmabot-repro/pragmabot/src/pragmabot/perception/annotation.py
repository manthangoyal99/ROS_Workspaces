"""Image annotation tool — numbered candidate-location overlays for the VLM.

Paper §IV.F: when the planner must choose among multiple candidate placement
or push targets, we overlay numbered markers and ask the VLM to pick one by
index. Pure PIL — no OpenCV dependency.
"""

from __future__ import annotations

import math
from typing import List, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFont

RGB = Tuple[int, int, int]
Pixel = Tuple[int, int]


def _to_pil(image: np.ndarray) -> Image.Image:
    if not isinstance(image, np.ndarray):
        raise TypeError(f"image must be np.ndarray, got {type(image).__name__}")
    arr = image
    if arr.dtype != np.uint8:
        arr = np.clip(arr, 0, 255).astype(np.uint8)
    if arr.ndim == 2:
        return Image.fromarray(arr, mode="L").convert("RGB")
    if arr.ndim == 3 and arr.shape[2] == 3:
        return Image.fromarray(arr, mode="RGB")
    if arr.ndim == 3 and arr.shape[2] == 4:
        return Image.fromarray(arr, mode="RGBA").convert("RGB")
    raise ValueError(f"unsupported image shape {arr.shape}")


def _from_pil(pil: Image.Image) -> np.ndarray:
    if pil.mode != "RGB":
        pil = pil.convert("RGB")
    return np.array(pil, dtype=np.uint8)


def _default_font() -> Optional[ImageFont.ImageFont]:
    """Best-effort font lookup: prefer DejaVuSans, fall back to PIL default."""
    candidates = (
        "DejaVuSans-Bold.ttf",
        "DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    )
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=16)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


class ImageAnnotator:
    """Draws numbered markers / mask overlays / bboxes on an RGB image."""

    def __init__(self, marker_radius: int = 14) -> None:
        self.marker_radius = int(marker_radius)
        self._font = _default_font()

    # ------------------------------------------------------------------
    # Candidate overlays
    # ------------------------------------------------------------------

    def annotate_candidates(
        self,
        image: np.ndarray,
        candidates: List[Pixel],
        style: str = "circle",
        color: RGB = (255, 0, 0),
    ) -> np.ndarray:
        """Draw numbered markers (1..N) at the given pixel coordinates."""
        pil = _to_pil(image).copy()
        draw = ImageDraw.Draw(pil)
        r = self.marker_radius

        for i, (u, v) in enumerate(candidates, start=1):
            u, v = int(u), int(v)
            if style == "arrow":
                # Draw an arrow from a fixed origin to (u, v) — for push
                # candidates. Origin is unknown here, so the user is expected
                # to draw via annotate_arrow separately. Fall back to circle.
                pass
            # Filled circle.
            draw.ellipse(
                (u - r, v - r, u + r, v + r),
                fill=color,
                outline=(0, 0, 0),
                width=2,
            )
            # Number label.
            label = str(i)
            try:
                tw = draw.textlength(label, font=self._font)
            except AttributeError:  # PIL < 9.2
                tw, _ = draw.textsize(label, font=self._font)  # type: ignore[attr-defined]
            draw.text(
                (u - tw / 2, v - r // 2 - 2),
                label,
                fill=(255, 255, 255),
                font=self._font,
            )
        return _from_pil(pil)

    def annotate_arrow(
        self,
        image: np.ndarray,
        start: Pixel,
        end: Pixel,
        label: str = "",
        color: RGB = (255, 0, 0),
        width: int = 4,
    ) -> np.ndarray:
        """Draw an arrow from ``start`` to ``end`` with an optional label."""
        pil = _to_pil(image).copy()
        draw = ImageDraw.Draw(pil)
        sx, sy = int(start[0]), int(start[1])
        ex, ey = int(end[0]), int(end[1])
        draw.line((sx, sy, ex, ey), fill=color, width=width)
        # Arrow head — two segments.
        angle = math.atan2(ey - sy, ex - sx)
        head = max(8, width * 3)
        for sign in (+1, -1):
            ha = angle + sign * math.radians(150)
            hx = ex + head * math.cos(ha)
            hy = ey + head * math.sin(ha)
            draw.line((ex, ey, hx, hy), fill=color, width=width)
        if label:
            draw.text((ex + 4, ey + 4), label, fill=color, font=self._font)
        return _from_pil(pil)

    # ------------------------------------------------------------------
    # Mask + bbox
    # ------------------------------------------------------------------

    def annotate_mask(
        self,
        image: np.ndarray,
        mask: np.ndarray,
        color: RGB = (0, 255, 0),
        alpha: float = 0.4,
    ) -> np.ndarray:
        """Alpha-blend a binary mask onto an image."""
        if mask is None:
            return image.copy()
        m = np.asarray(mask).astype(bool)
        if m.shape != image.shape[:2]:
            raise ValueError(
                f"mask shape {m.shape} does not match image {image.shape[:2]}"
            )
        a = float(np.clip(alpha, 0.0, 1.0))
        overlay = np.array(color, dtype=np.float32)
        base = image.astype(np.float32).copy()
        base[m] = base[m] * (1 - a) + overlay * a
        return np.clip(base, 0, 255).astype(np.uint8)

    def draw_bbox(
        self,
        image: np.ndarray,
        bbox: Tuple[int, int, int, int],
        label: str = "",
        color: RGB = (0, 0, 255),
    ) -> np.ndarray:
        """Draw a rectangular bounding box with an optional label."""
        pil = _to_pil(image).copy()
        draw = ImageDraw.Draw(pil)
        x1, y1, x2, y2 = (int(v) for v in bbox)
        draw.rectangle((x1, y1, x2, y2), outline=color, width=3)
        if label:
            draw.text((x1 + 2, max(0, y1 - 18)), label, fill=color, font=self._font)
        return _from_pil(pil)

    # ------------------------------------------------------------------
    # Candidate generators
    # ------------------------------------------------------------------

    @staticmethod
    def generate_push_candidates(
        object_centroid: Pixel,
        n_directions: int = 4,
        distance_px: int = 80,
    ) -> List[Pixel]:
        """Sample ``n_directions`` evenly-spaced endpoint pixels around a centroid."""
        if n_directions <= 0:
            return []
        cu, cv = int(object_centroid[0]), int(object_centroid[1])
        out: List[Pixel] = []
        for i in range(int(n_directions)):
            theta = 2 * math.pi * i / int(n_directions)
            u = int(round(cu + distance_px * math.cos(theta)))
            v = int(round(cv + distance_px * math.sin(theta)))
            out.append((u, v))
        return out
