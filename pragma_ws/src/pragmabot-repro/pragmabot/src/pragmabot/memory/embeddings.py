"""Text embedding abstractions and concrete backends."""

from __future__ import annotations

import hashlib
import logging
import os
import struct
from abc import ABC, abstractmethod
from typing import List

import numpy as np
from omegaconf import DictConfig

logger = logging.getLogger(__name__)


class BaseEmbedder(ABC):
    """Abstract base class for text embedders."""

    @abstractmethod
    def embed(self, text: str) -> np.ndarray:
        """Embed a single string into a 1-D float32 vector."""

    @abstractmethod
    def embed_batch(self, texts: List[str]) -> np.ndarray:
        """Embed a list of strings into an (N, D) float32 matrix."""

    @property
    @abstractmethod
    def dim(self) -> int:
        """Embedding dimensionality."""

    @property
    @abstractmethod
    def backend_name(self) -> str:
        """Short backend identifier."""


class StubEmbedder(BaseEmbedder):
    """Deterministic stub embedder.

    Hashes the input text to seed a fixed-dim float vector. Same text always
    gives the same vector across processes and machines.
    """

    def __init__(self, dim: int = 64) -> None:
        if dim <= 0:
            raise ValueError("dim must be positive")
        self._dim = int(dim)

    @property
    def dim(self) -> int:
        return self._dim

    @property
    def backend_name(self) -> str:
        return "stub"

    def _vector_for(self, text: str) -> np.ndarray:
        # Stretch the SHA-256 digest into ``dim`` floats deterministically.
        raw = text.encode("utf-8")
        out = np.empty(self._dim, dtype=np.float32)
        i = 0
        counter = 0
        while i < self._dim:
            h = hashlib.sha256(raw + counter.to_bytes(4, "big")).digest()
            # 8 floats per 32-byte digest (4 bytes each)
            for j in range(0, 32, 4):
                if i >= self._dim:
                    break
                # Map uint32 to [-1, 1]
                (u,) = struct.unpack(">I", h[j : j + 4])
                out[i] = (u / 0xFFFFFFFF) * 2.0 - 1.0
                i += 1
            counter += 1
        # L2-normalize for stable cosine similarity behaviour.
        norm = float(np.linalg.norm(out))
        if norm > 0:
            out /= norm
        return out

    def embed(self, text: str) -> np.ndarray:
        return self._vector_for(text)

    def embed_batch(self, texts: List[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self._dim), dtype=np.float32)
        return np.stack([self._vector_for(t) for t in texts], axis=0)


class SentenceTransformerEmbedder(BaseEmbedder):
    """Local, free embeddings via the sentence-transformers package."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "sentence-transformers is not installed. "
                "Install it or use the stub embedder."
            ) from exc
        self._model = SentenceTransformer(model_name)
        self._model_name = model_name
        # Probe dimensionality.
        probe = self._model.encode(["probe"], convert_to_numpy=True)
        self._dim = int(probe.shape[1])

    @property
    def dim(self) -> int:
        return self._dim

    @property
    def backend_name(self) -> str:
        return "sentence_transformers"

    def embed(self, text: str) -> np.ndarray:
        vec = self._model.encode([text], convert_to_numpy=True, normalize_embeddings=True)
        return vec[0].astype(np.float32)

    def embed_batch(self, texts: List[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self._dim), dtype=np.float32)
        mat = self._model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
        return mat.astype(np.float32)


class OpenAIEmbedder(BaseEmbedder):
    """OpenAI text embeddings backend."""

    def __init__(self, model: str = "text-embedding-3-large") -> None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set; cannot use OpenAI embedder.")
        try:
            from openai import OpenAI  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise ImportError("openai SDK is not installed.") from exc
        self._client = OpenAI(api_key=api_key)
        self._model = model
        # Will be set on first call.
        self._dim = 0

    @property
    def dim(self) -> int:
        if self._dim == 0:
            # Lazy probe.
            _ = self.embed("probe")
        return self._dim

    @property
    def backend_name(self) -> str:
        return "openai"

    def embed(self, text: str) -> np.ndarray:
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: List[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self._dim or 1), dtype=np.float32)
        resp = self._client.embeddings.create(model=self._model, input=texts)
        mat = np.array([d.embedding for d in resp.data], dtype=np.float32)
        self._dim = int(mat.shape[1])
        return mat


def get_embedder(cfg: DictConfig) -> BaseEmbedder:
    """Instantiate an embedder from the ``embeddings`` section of a config.

    Backends are resolved via the global :data:`pragmabot.registry.registry`;
    custom backends register themselves under ``"embedder"`` to become
    available here.
    """
    from ..registry import registry

    emb_cfg = cfg.embeddings
    backend = str(emb_cfg.get("backend", "stub")).lower()
    model = str(emb_cfg.get("model", "all-MiniLM-L6-v2"))

    cls = registry.get("embedder", backend)
    if backend == "stub":
        dim = int(emb_cfg.get("dim", 64))
        return cls(dim=dim)
    if backend == "sentence_transformers":
        return cls(model_name=model)
    if backend == "openai":
        return cls(model=model)
    # Custom backends are passed the whole config.
    return cls(cfg)
