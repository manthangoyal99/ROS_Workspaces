"""Long-term memory manager with cosine-similarity retrieval.

Storage format:
- ``ltm.csv``: rows of ``time,key,experience`` (UTF-8, header).
- ``<embeddings_path>``: a NumPy ``.npy`` matrix of shape (N, D) aligned with
  the CSV row order.

The CSV mirrors the upstream PragmaBot text format while the .npy file keeps
embeddings backend-agnostic.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Dict, List, Optional, Union

import numpy as np
from omegaconf import DictConfig

from ..utils import ensure_dir, get_repo_root, get_timestamp
from .embeddings import BaseEmbedder

logger = logging.getLogger(__name__)


def _resolve_path(p: Union[str, Path]) -> Path:
    """Resolve a path relative to the repo root if not absolute."""
    path = Path(p)
    if path.is_absolute():
        return path
    return get_repo_root() / path


class MemoryManager:
    """In-memory LTM with disk persistence.

    Stores ``(key, experience, embedding)`` triples. ``retrieve`` ranks the
    stored entries by cosine similarity against the query key's embedding.
    """

    CSV_HEADER = ["time", "key", "experience"]

    def __init__(self, cfg: DictConfig, embedder: BaseEmbedder) -> None:
        self.cfg = cfg
        self.embedder = embedder

        mem_cfg = cfg.memory
        self.ltm_path = _resolve_path(mem_cfg.get("ltm_path", "pragmabot/data/ltm/ltm.csv"))
        self.embeddings_path = _resolve_path(
            mem_cfg.get("embeddings_path", "pragmabot/data/ltm/ltm_embeddings.npy")
        )
        self.top_k: int = int(mem_cfg.get("top_k", 3))

        self._times: List[str] = []
        self._keys: List[str] = []
        self._experiences: List[str] = []
        # (N, D) float32, or None when empty.
        self._embeddings: Optional[np.ndarray] = None

        self.load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._keys)

    def clear(self) -> None:
        """Clear the in-memory LTM (does not touch files)."""
        self._times = []
        self._keys = []
        self._experiences = []
        self._embeddings = None

    def store(self, key: str, experience: str) -> None:
        """Embed ``key`` and append a new entry; persists to disk."""
        if not isinstance(key, str) or not isinstance(experience, str):
            raise TypeError("key and experience must be strings")

        vec = np.asarray(self.embedder.embed(key), dtype=np.float32)
        if vec.ndim != 1:
            raise ValueError(f"Embedder returned non-1D vector: shape={vec.shape}")

        self._times.append(get_timestamp())
        self._keys.append(key)
        self._experiences.append(experience)

        if self._embeddings is None:
            self._embeddings = vec.reshape(1, -1)
        else:
            if vec.shape[0] != self._embeddings.shape[1]:
                raise ValueError(
                    f"Embedding dim mismatch: existing={self._embeddings.shape[1]}, new={vec.shape[0]}"
                )
            self._embeddings = np.vstack([self._embeddings, vec.reshape(1, -1)])

        self.save()

    def retrieve(self, query_key: str, top_k: Optional[int] = None) -> List[Dict[str, object]]:
        """Return the top-k entries most similar to ``query_key``.

        Returns:
            List of ``{"key": str, "experience": str, "similarity": float, "time": str}``.
        """
        if top_k is None:
            top_k = self.top_k
        if top_k <= 0 or len(self) == 0 or self._embeddings is None:
            return []

        q = np.asarray(self.embedder.embed(query_key), dtype=np.float32)
        sims = self._cosine_sim_matrix(self._embeddings, q)
        order = np.argsort(-sims)[: int(top_k)]

        out: List[Dict[str, object]] = []
        for i in order:
            out.append(
                {
                    "key": self._keys[i],
                    "experience": self._experiences[i],
                    "similarity": float(sims[i]),
                    "time": self._times[i],
                }
            )
        return out

    def load(self) -> None:
        """Load LTM from CSV + embeddings .npy, if present."""
        self.clear()
        if not self.ltm_path.exists():
            logger.info("No LTM CSV found at %s — starting empty.", self.ltm_path)
            return

        with self.ltm_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                self._times.append(row.get("time", ""))
                self._keys.append(row.get("key", ""))
                self._experiences.append(row.get("experience", ""))

        if self.embeddings_path.exists() and self._keys:
            mat = np.load(self.embeddings_path)
            if mat.shape[0] != len(self._keys):
                logger.warning(
                    "Embedding/CSV row count mismatch (%d vs %d) — re-embedding from keys.",
                    mat.shape[0],
                    len(self._keys),
                )
                mat = self.embedder.embed_batch(list(self._keys)).astype(np.float32)
            self._embeddings = mat.astype(np.float32)
        elif self._keys:
            logger.info("Embeddings file missing — computing embeddings for %d keys.", len(self._keys))
            self._embeddings = self.embedder.embed_batch(list(self._keys)).astype(np.float32)
        else:
            self._embeddings = None

        logger.info("Loaded %d LTM entries from %s.", len(self), self.ltm_path)

    def save(self) -> None:
        """Write the current in-memory LTM to disk (CSV + .npy)."""
        ensure_dir(self.ltm_path.parent)
        with self.ltm_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=self.CSV_HEADER)
            writer.writeheader()
            for t, k, e in zip(self._times, self._keys, self._experiences):
                writer.writerow({"time": t, "key": k, "experience": e})

        ensure_dir(self.embeddings_path.parent)
        if self._embeddings is not None and self._embeddings.size > 0:
            np.save(self.embeddings_path, self._embeddings.astype(np.float32))
        else:
            # Remove any stale embeddings file so load() stays consistent.
            try:
                self.embeddings_path.unlink(missing_ok=True)
            except (PermissionError, OSError) as exc:
                logger.warning("Could not unlink stale embeddings file %s: %s", self.embeddings_path, exc)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _cosine_sim_matrix(mat: np.ndarray, vec: np.ndarray) -> np.ndarray:
        """Cosine similarity of each row of ``mat`` against ``vec``."""
        if mat.size == 0:
            return np.zeros((0,), dtype=np.float32)
        mat_norm = np.linalg.norm(mat, axis=1)
        vec_norm = float(np.linalg.norm(vec))
        if vec_norm == 0.0:
            return np.zeros((mat.shape[0],), dtype=np.float32)
        denom = mat_norm * vec_norm
        denom = np.where(denom == 0.0, 1.0, denom)
        return (mat @ vec) / denom
