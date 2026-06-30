"""Phase 0 Mac smoke tests — zero ROS dependencies, stub backends only."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from omegaconf import OmegaConf

from pragmabot.memory.embeddings import StubEmbedder, get_embedder
from pragmabot.memory.memory_manager import MemoryManager
from pragmabot.pipeline import PragmaBot
from pragmabot.simple_config import load_config
from pragmabot.vlm.factory import get_vlm
from pragmabot.vlm.stub_vlm import StubVLM


REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "pragmabot" / "config" / "config.yaml"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stub_cfg(tmp_path: Path):
    """Build a minimal in-memory config that points LTM paths at tmp_path."""
    base = load_config(CONFIG_PATH)
    base.memory.ltm_path = str(tmp_path / "ltm.csv")
    base.memory.embeddings_path = str(tmp_path / "ltm_embeddings.npy")
    base.vlm.backend = "stub"
    base.embeddings.backend = "stub"
    base.embeddings.dim = 32
    base.robot.backend = "stub"
    return base


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_config_loads():
    cfg = load_config(CONFIG_PATH)
    for key in ("mode", "vlm", "embeddings", "perception", "robot", "memory"):
        assert key in cfg, f"missing key {key} in config"
    assert cfg.vlm.backend in {"stub", "ollama", "openai"}
    assert cfg.robot.backend in {"stub", "franka_ros"}


def test_stub_vlm_deterministic():
    vlm = StubVLM()
    msgs = [{"role": "user", "content": "Plan the next action for the robot."}]
    a = vlm.chat(msgs)
    b = vlm.chat(msgs)
    assert isinstance(a, str) and len(a) > 0
    assert a == b


def test_stub_vlm_with_image():
    vlm = StubVLM()
    img = np.zeros((4, 4, 3), dtype=np.uint8)
    msgs = [{"role": "user", "content": "Describe the scene."}]
    out = vlm.chat_with_image(msgs, [img])
    assert isinstance(out, str) and len(out) > 0


def test_stub_embedder_shape():
    emb = StubEmbedder(dim=32)
    v = emb.embed("hello world")
    assert v.shape == (32,)
    batch = emb.embed_batch(["a", "b", "c"])
    assert batch.shape == (3, 32)


def test_stub_embedder_deterministic():
    emb = StubEmbedder(dim=32)
    v1 = emb.embed("pick up the apple")
    v2 = emb.embed("pick up the apple")
    assert np.allclose(v1, v2)
    # Different text → different vector.
    v3 = emb.embed("place the cup")
    assert not np.allclose(v1, v3)


def test_get_embedder_factory(tmp_path):
    cfg = _stub_cfg(tmp_path)
    emb = get_embedder(cfg)
    assert emb.backend_name == "stub"
    assert emb.dim == 32


def test_get_vlm_factory(tmp_path):
    cfg = _stub_cfg(tmp_path)
    vlm = get_vlm(cfg)
    assert vlm.backend_name == "stub"


def test_memory_store_retrieve(tmp_path):
    cfg = _stub_cfg(tmp_path)
    mem = MemoryManager(cfg, embedder=StubEmbedder(dim=32))

    mem.store("pick up the apple from the left side", "Picked apple successfully.")
    mem.store("place the blue cup on the shelf", "Placed cup successfully.")
    mem.store("push the wooden block forward", "Pushed block successfully.")

    assert len(mem) == 3

    # Querying with an exact stored key must retrieve that same entry first.
    target_key = "place the blue cup on the shelf"
    results = mem.retrieve(target_key, top_k=3)
    assert len(results) == 3
    assert results[0]["key"] == target_key
    assert results[0]["similarity"] == pytest.approx(1.0, abs=1e-5)
    # Sorted descending by similarity.
    sims = [r["similarity"] for r in results]
    assert sims == sorted(sims, reverse=True)


def test_memory_persistence(tmp_path):
    cfg = _stub_cfg(tmp_path)
    embedder = StubEmbedder(dim=32)

    mem = MemoryManager(cfg, embedder=embedder)
    mem.store("pick the red apple", "Done.")
    mem.store("place the cup", "Done.")
    mem.save()

    # Fresh instance loads the same data.
    mem2 = MemoryManager(cfg, embedder=embedder)
    assert len(mem2) == 2
    results = mem2.retrieve("pick the red apple", top_k=1)
    assert results and "apple" in results[0]["key"].lower()

    # clear() drops in-memory state but disk still has it; load restores.
    mem2.clear()
    assert len(mem2) == 0
    mem2.load()
    assert len(mem2) == 2


def test_pipeline_skeleton_runs(tmp_path):
    cfg = _stub_cfg(tmp_path)
    cfg.pipeline.max_steps = 2
    bot = PragmaBot(cfg)

    def get_observation():
        return np.zeros((480, 640, 3), dtype=np.uint8)

    result = bot.run_task("pick up the apple", get_observation)

    assert set(result.keys()) >= {"success", "steps", "stm", "experience"}
    assert isinstance(result["success"], bool)
    assert isinstance(result["steps"], int) and result["steps"] >= 1
    assert isinstance(result["stm"], list) and len(result["stm"]) >= 1
    assert isinstance(result["experience"], str) and len(result["experience"]) > 0


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
