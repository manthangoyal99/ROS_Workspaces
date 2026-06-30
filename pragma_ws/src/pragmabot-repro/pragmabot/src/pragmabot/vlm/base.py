"""Abstract VLM backend interface."""

from __future__ import annotations

import base64
import io
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import numpy as np


class BaseVLM(ABC):
    """Abstract base class for vision-language model backends.

    Subclasses MUST call :meth:`_record_exchange` after each chat call so the
    pipeline's per-task conversation log captures the (prompt, response, images)
    triples. The conversation list is reset between tasks by the pipeline.
    """

    def __init__(self) -> None:
        # Tagged exchanges accumulated across all chat calls. Each entry:
        #   {"stage": str | None, "step": int | None,
        #    "messages": [...], "response": str,
        #    "images_b64": [str, ...], "timestamp": float}
        self.conversation: List[Dict[str, Any]] = []
        # Optional default tag values; the pipeline sets these via
        # ``set_conversation_tag`` so subsequent VLM calls inherit the tags.
        self._tag_stage: Optional[str] = None
        self._tag_step: Optional[int] = None

    # ------------------------------------------------------------------
    # Conversation capture
    # ------------------------------------------------------------------

    def set_conversation_tag(self, *, stage: Optional[str] = None,
                             step: Optional[int] = None) -> None:
        """Tag subsequent ``_record_exchange`` calls with stage + step."""
        if stage is not None:
            self._tag_stage = stage
        if step is not None:
            self._tag_step = step

    def reset_conversation(self) -> None:
        """Clear the conversation log (called at task start by the pipeline)."""
        self.conversation = []
        self._tag_stage = None
        self._tag_step = None

    @staticmethod
    def _thumbnail_b64(image: np.ndarray, max_side: int = 320) -> str:
        """Encode an RGB uint8 image to a base64 PNG thumbnail."""
        try:
            from PIL import Image  # type: ignore
        except ImportError:
            return ""
        if not isinstance(image, np.ndarray) or image.ndim != 3:
            return ""
        arr = image
        if arr.dtype != np.uint8:
            arr = np.clip(arr, 0, 255).astype(np.uint8)
        h, w = arr.shape[:2]
        if max(h, w) > max_side:
            scale = max_side / max(h, w)
            new_w, new_h = int(w * scale), int(h * scale)
            pil = Image.fromarray(arr).resize((new_w, new_h))
        else:
            pil = Image.fromarray(arr)
        buf = io.BytesIO()
        pil.save(buf, format="PNG", optimize=True)
        return base64.b64encode(buf.getvalue()).decode("ascii")

    def _record_exchange(
        self,
        messages: List[Dict[str, Any]],
        response: str,
        images: Optional[List[np.ndarray]] = None,
    ) -> None:
        """Append one (prompt, response, images) entry to the conversation log."""
        entry: Dict[str, Any] = {
            "stage": self._tag_stage,
            "step": self._tag_step,
            "timestamp": time.time(),
            "messages": [
                {"role": m.get("role", "user"), "content": m.get("content", "")}
                for m in messages
            ],
            "response": response if isinstance(response, str) else str(response),
            "images_b64": [],
        }
        if images:
            for img in images:
                if isinstance(img, np.ndarray):
                    b64 = self._thumbnail_b64(img)
                    if b64:
                        entry["images_b64"].append(b64)
        self.conversation.append(entry)

    # ------------------------------------------------------------------
    # Abstract API
    # ------------------------------------------------------------------

    @abstractmethod
    def chat(self, messages: List[dict]) -> str:
        """Send a text-only chat request and return the assistant response."""

    @abstractmethod
    def chat_with_image(self, messages: List[dict], images: List[np.ndarray]) -> str:
        """Send a chat request with one or more attached images."""

    @property
    @abstractmethod
    def backend_name(self) -> str:
        """Short identifier of the backend (e.g., ``"stub"``, ``"ollama"``)."""
