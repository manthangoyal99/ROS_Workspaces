"""OpenAI VLM backend — supports GPT-4o vision."""

from __future__ import annotations

import logging
import os
from typing import List

import numpy as np

from ..utils import encode_image_to_base64
from .base import BaseVLM

logger = logging.getLogger(__name__)


class OpenAINotConfiguredError(RuntimeError):
    """Raised when OPENAI_API_KEY is missing or the openai SDK cannot be used."""


class OpenAIVLM(BaseVLM):
    """OpenAI Chat Completions backend (text + vision)."""

    def __init__(
        self,
        model: str = "gpt-4o-2024-08-06",
        temperature: float = 0.0,
        max_tokens: int = 512,
    ) -> None:
        super().__init__()
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise OpenAINotConfiguredError("OPENAI_API_KEY is not set in the environment.")
        try:
            from openai import OpenAI  # type: ignore
        except ImportError as exc:  # pragma: no cover - import guard
            raise OpenAINotConfiguredError(
                "openai SDK is not installed. Add `openai` to requirements."
            ) from exc
        self._client = OpenAI(api_key=api_key)
        self.model = model
        self.temperature = float(temperature)
        self.max_tokens = int(max_tokens)

    @property
    def backend_name(self) -> str:
        return "openai"

    def _call(self, messages: List[dict]) -> str:
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        return resp.choices[0].message.content or ""

    def chat(self, messages: List[dict]) -> str:
        resp = self._call(messages)
        self._record_exchange(messages, resp, images=None)
        return resp

    def chat_with_image(self, messages: List[dict], images: List[np.ndarray]) -> str:
        original_messages = messages
        if not images:
            resp = self._call(messages)
            self._record_exchange(messages, resp, images=None)
            return resp

        msgs = [dict(m) for m in messages]
        if not msgs or msgs[-1].get("role") != "user":
            msgs.append({"role": "user", "content": ""})

        last = msgs[-1]
        text = last.get("content", "")
        parts: List[dict] = []
        if isinstance(text, str) and text:
            parts.append({"type": "text", "text": text})
        elif isinstance(text, list):
            parts.extend(text)
        for img in images:
            data_uri = encode_image_to_base64(img, image_format="JPEG")
            parts.append({"type": "image_url", "image_url": {"url": data_uri}})
        last["content"] = parts

        resp = self._call(msgs)
        # Log with the human-readable text messages (not the inlined base64).
        self._record_exchange(original_messages, resp, images=images)
        return resp
