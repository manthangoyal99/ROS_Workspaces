"""Grounded SAM perception backend — Ubuntu + GPU only.

Heavy dependencies are guarded so that Mac imports succeed even without
torch / SAM / GroundingDINO installed; calling ``GroundedSAMPerception(cfg)``
on Mac raises a clear ImportError instead.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

import numpy as np
from omegaconf import DictConfig

from .base import BasePerception, DetectedObject, PerceptionResult
from .camera_intrinsics import CameraIntrinsics, unproject_pixel

logger = logging.getLogger(__name__)


# --- Heavy-deps guard ---------------------------------------------------------
# Mac will hit ImportError here and set GROUNDED_SAM_AVAILABLE = False; the
# module still imports cleanly.
try:
    import torch  # type: ignore
    from groundingdino.util.inference import (  # type: ignore
        load_model as _gd_load_model,
        predict as _gd_predict,
    )
    from segment_anything import (  # type: ignore
        sam_model_registry as _sam_model_registry,
        SamPredictor as _SamPredictor,
    )

    GROUNDED_SAM_AVAILABLE = True
except ImportError:
    torch = None  # type: ignore
    _gd_load_model = None  # type: ignore
    _gd_predict = None  # type: ignore
    _sam_model_registry = None  # type: ignore
    _SamPredictor = None  # type: ignore
    GROUNDED_SAM_AVAILABLE = False
# -----------------------------------------------------------------------------


class GroundedSAMPerception(BasePerception):
    """Open-vocabulary detection via Grounding DINO + segmentation via SAM."""

    def __init__(self, cfg: DictConfig) -> None:
        if not GROUNDED_SAM_AVAILABLE:
            raise ImportError(
                "Grounded SAM dependencies not installed. Required: torch, "
                "groundingdino-py, segment-anything. See docs/setup_ubuntu.md."
            )

        self.cfg = cfg
        perc = cfg.perception
        self.box_threshold: float = float(perc.get("confidence_threshold", 0.3))
        self.text_threshold: float = float(perc.get("text_threshold", 0.25))
        self.device: str = str(perc.get("device", "cuda"))

        gd_config = str(perc.get("grounding_dino_config", "") or "")
        gd_ckpt = str(perc.get("grounding_dino_checkpoint", "") or "")
        sam_ckpt = str(perc.get("sam_checkpoint", "") or "")
        sam_type = str(perc.get("sam_model_type", "vit_b"))

        for label, path in (("grounding_dino_config", gd_config),
                            ("grounding_dino_checkpoint", gd_ckpt),
                            ("sam_checkpoint", sam_ckpt)):
            if not path or not Path(path).exists():
                raise FileNotFoundError(
                    f"perception.{label} missing or does not exist: {path!r}"
                )

        logger.info("Loading Grounding DINO (%s)", gd_ckpt)
        self._gd_model = _gd_load_model(gd_config, gd_ckpt)
        self._gd_model = self._gd_model.to(self.device)

        logger.info("Loading SAM (%s, %s)", sam_type, sam_ckpt)
        sam_model = _sam_model_registry[sam_type](checkpoint=sam_ckpt)
        sam_model.to(self.device)
        self._sam_predictor = _SamPredictor(sam_model)

        try:
            self._intrinsics: Optional[CameraIntrinsics] = CameraIntrinsics.from_config(cfg)
        except Exception:  # pragma: no cover - intrinsics optional
            self._intrinsics = None

    @property
    def backend_name(self) -> str:
        return "grounded_sam"

    def is_available(self) -> bool:
        return GROUNDED_SAM_AVAILABLE

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    def detect(
        self,
        rgb: np.ndarray,
        queries: List[str],
        depth: Optional[np.ndarray] = None,
    ) -> PerceptionResult:  # pragma: no cover - exercised on Ubuntu only
        if not isinstance(rgb, np.ndarray) or rgb.ndim != 3 or rgb.shape[2] != 3:
            raise ValueError(f"rgb must be HxWx3, got shape {rgb.shape}")

        prompt = " . ".join(q.strip().lower() for q in queries if q.strip())
        if not prompt:
            return PerceptionResult(objects=[], raw_depth=depth)

        # GroundingDINO expects a tensor (3, H, W) in [0, 1].
        image_tensor = (
            torch.from_numpy(rgb).permute(2, 0, 1).float() / 255.0
        ).to(self.device)

        boxes, logits, phrases = _gd_predict(
            model=self._gd_model,
            image=image_tensor,
            caption=prompt,
            box_threshold=self.box_threshold,
            text_threshold=self.text_threshold,
            device=self.device,
        )

        # Boxes from GroundingDINO are normalized (cx, cy, w, h) in [0, 1].
        h, w = rgb.shape[:2]
        boxes_xyxy = []
        for b in boxes.cpu().numpy():
            cx, cy, bw, bh = b
            x1 = int(round((cx - bw / 2) * w))
            y1 = int(round((cy - bh / 2) * h))
            x2 = int(round((cx + bw / 2) * w))
            y2 = int(round((cy + bh / 2) * h))
            boxes_xyxy.append((max(0, x1), max(0, y1), min(w, x2), min(h, y2)))

        self._sam_predictor.set_image(rgb)
        objects: List[DetectedObject] = []
        for (x1, y1, x2, y2), conf, phrase in zip(boxes_xyxy, logits.cpu().tolist(), phrases):
            masks, _, _ = self._sam_predictor.predict(
                box=np.array([x1, y1, x2, y2]),
                multimask_output=False,
            )
            mask = masks[0].astype(bool) if masks is not None and len(masks) > 0 else None

            cu = (x1 + x2) // 2
            cv = (y1 + y2) // 2
            centroid_3d = None
            if depth is not None and self._intrinsics is not None:
                centroid_3d = unproject_pixel(cu, cv, depth, self._intrinsics)

            objects.append(
                DetectedObject(
                    name=phrase,
                    confidence=float(conf),
                    bbox_2d=(x1, y1, x2, y2),
                    mask=mask,
                    centroid_2d=(cu, cv),
                    centroid_3d=centroid_3d,
                    extras={"backend": "grounded_sam", "phrase": phrase},
                )
            )

        return PerceptionResult(objects=objects, raw_depth=depth)
