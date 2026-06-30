"""Shared utility functions — image encoding, paths, timestamps."""

from __future__ import annotations

import base64
import io
import logging
from datetime import datetime
from pathlib import Path
from typing import Union

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

PathLike = Union[str, Path]


def get_package_path() -> Path:
    """Return the root path of the pragmabot ROS-style package directory.

    Layout: ``<repo>/pragmabot/src/pragmabot/utils.py`` → package root is
    ``<repo>/pragmabot``.
    """
    return Path(__file__).resolve().parents[2]


def get_repo_root() -> Path:
    """Return the repository root (one level above the package directory)."""
    return get_package_path().parent


def ensure_dir(path: PathLike) -> None:
    """Create the directory (and parents) if it does not already exist."""
    Path(path).mkdir(parents=True, exist_ok=True)


def get_timestamp() -> str:
    """Return the current local timestamp as ``YYYY-MM-DD HH:MM:SS``."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def encode_image_to_base64(image: np.ndarray, image_format: str = "JPEG", quality: int = 85) -> str:
    """Encode an HxWx3 (or HxW) NumPy image to a base64 data URI.

    Args:
        image: RGB uint8 array of shape (H, W, 3), or grayscale (H, W).
        image_format: ``"JPEG"`` or ``"PNG"``.
        quality: JPEG quality (ignored for PNG).

    Returns:
        ``data:<mime>;base64,...`` string.
    """
    if image is None:
        raise ValueError("Image cannot be None")
    if not isinstance(image, np.ndarray):
        raise TypeError(f"Expected np.ndarray, got {type(image).__name__}")

    arr = image
    if arr.dtype != np.uint8:
        arr = np.clip(arr, 0, 255).astype(np.uint8)

    if arr.ndim == 2:
        pil = Image.fromarray(arr, mode="L").convert("RGB")
    elif arr.ndim == 3 and arr.shape[2] == 3:
        pil = Image.fromarray(arr, mode="RGB")
    elif arr.ndim == 3 and arr.shape[2] == 4:
        pil = Image.fromarray(arr, mode="RGBA").convert("RGB")
    else:
        raise ValueError(f"Unsupported image shape: {arr.shape}")

    buf = io.BytesIO()
    fmt = image_format.upper()
    if fmt == "JPEG":
        pil.save(buf, format="JPEG", quality=quality, optimize=True)
        mime = "image/jpeg"
    elif fmt == "PNG":
        pil.save(buf, format="PNG", optimize=True)
        mime = "image/png"
    else:
        raise ValueError(f"Unsupported image_format: {image_format}")

    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def decode_base64_to_image(b64: str) -> np.ndarray:
    """Decode a base64 (optionally data-URI) string into an RGB uint8 array."""
    if b64 is None:
        raise ValueError("base64 string cannot be None")
    payload = b64
    if payload.startswith("data:"):
        # data:<mime>;base64,<...>
        _, _, payload = payload.partition(",")
    raw = base64.b64decode(payload)
    pil = Image.open(io.BytesIO(raw)).convert("RGB")
    return np.array(pil, dtype=np.uint8)


def load_image_from_path(path: PathLike) -> np.ndarray:
    """Load an image from disk as an RGB uint8 NumPy array."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Image not found: {p}")
    pil = Image.open(p).convert("RGB")
    return np.array(pil, dtype=np.uint8)


def get_scenario_key(instruction: str, initial_scene_description: str) -> str:
    """Format instruction + scene into a stable LTM retrieval key."""
    return f"Instruction: {instruction}\nScene: {initial_scene_description}"
