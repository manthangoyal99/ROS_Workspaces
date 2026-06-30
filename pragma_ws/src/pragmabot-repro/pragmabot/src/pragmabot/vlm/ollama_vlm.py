"""Ollama VLM backend — local, free, multimodal."""

from __future__ import annotations

import base64
import io
import logging
from typing import List

import numpy as np
import requests
from PIL import Image

from .base import BaseVLM

logger = logging.getLogger(__name__)


class OllamaNotAvailableError(RuntimeError):
    """Raised when the Ollama server is unreachable."""


class OllamaVLM(BaseVLM):
    """Talk to a local Ollama server via its HTTP API.

    Uses ``POST /api/chat`` with the ``images`` field for multimodal inputs.
    """

    def __init__(
        self,
        model: str = "llava:7b",
        host: str = "http://localhost:11434",
        temperature: float = 0.0,
        max_tokens: int = 512,
        timeout_s: float = 120.0,
    ) -> None:
        super().__init__()
        self.model = model
        self.host = host.rstrip("/")
        self.temperature = float(temperature)
        self.max_tokens = int(max_tokens)
        self.timeout_s = float(timeout_s)

    @property
    def backend_name(self) -> str:
        return "ollama"

    @staticmethod
    def _encode_image_b64(image: np.ndarray) -> str:
        """Encode an RGB uint8 array as a raw base64 string (no data URI)."""
        if not isinstance(image, np.ndarray):
            raise TypeError(f"Expected np.ndarray, got {type(image).__name__}")
        arr = image
        if arr.dtype != np.uint8:
            arr = np.clip(arr, 0, 255).astype(np.uint8)
        if arr.ndim == 2:
            pil = Image.fromarray(arr, mode="L").convert("RGB")
        else:
            pil = Image.fromarray(arr, mode="RGB")
        buf = io.BytesIO()
        pil.save(buf, format="JPEG", quality=85, optimize=True)
        return base64.b64encode(buf.getvalue()).decode("ascii")

    def _post(self, payload: dict) -> dict:
        url = f"{self.host}/api/chat"
        try:
            r = requests.post(url, json=payload, timeout=self.timeout_s)
        except requests.exceptions.RequestException as exc:
            raise OllamaNotAvailableError(f"Failed to reach Ollama at {url}: {exc}") from exc
        if r.status_code != 200:
            raise OllamaNotAvailableError(
                f"Ollama returned HTTP {r.status_code} at {url}: {r.text[:200]}"
            )
        return r.json()

    def _build_payload(self, messages: List[dict], images: List[np.ndarray] | None) -> dict:
        msgs = [dict(m) for m in messages]
        if images:
            if not msgs or msgs[-1].get("role") != "user":
                msgs.append({"role": "user", "content": ""})
            msgs[-1]["images"] = [self._encode_image_b64(img) for img in images]
        return {
            "model": self.model,
            "messages": msgs,
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_predict": self.max_tokens,
            },
        }

    def chat(self, messages: List[dict]) -> str:
        resp = self._post(self._build_payload(messages, images=None))
        out = resp.get("message", {}).get("content", "")
        self._record_exchange(messages, out, images=None)
        return out

    def chat_with_image(self, messages: List[dict], images: List[np.ndarray]) -> str:
        resp = self._post(self._build_payload(messages, images=images))
        out = resp.get("message", {}).get("content", "")
        self._record_exchange(messages, out, images=images)
        return out
