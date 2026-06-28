#!/usr/bin/env python3
"""Standalone ROS node for inspecting the long-term memory."""

from __future__ import annotations

# --- ROS import guard (per CLAUDE.md) ----------------------------------------
try:
    import rospy  # type: ignore

    ROS_AVAILABLE = True
except ImportError:
    ROS_AVAILABLE = False
# -----------------------------------------------------------------------------

import logging
import sys
import tempfile
import threading
from pathlib import Path
from typing import List

# Add src/ to sys.path so this script runs under catkin or standalone.
_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import numpy as np  # noqa: E402

from pragmabot.memory.embeddings import get_embedder  # noqa: E402
from pragmabot.memory.memory_manager import MemoryManager  # noqa: E402
from pragmabot.simple_config import load_config  # noqa: E402


logger = logging.getLogger(__name__)


def _require_ros() -> None:
    if not ROS_AVAILABLE:
        raise RuntimeError("ROS not available — memory_manager_node requires rospy.")


class MemoryManagerNode:
    """ROS node that wraps a MemoryManager with a Gradio inspector UI."""

    def __init__(self, config_path: str = None) -> None:
        _require_ros()
        if not rospy.core.is_initialized():
            rospy.init_node("memory_manager", anonymous=False)
        if config_path is None:
            config_path = rospy.get_param(
                "~config_path", str(_SRC.parent / "config" / "config.yaml")
            )
        self.cfg = load_config(config_path)
        self.embedder = get_embedder(self.cfg)
        self.memory = MemoryManager(self.cfg, self.embedder)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Data helpers
    # ------------------------------------------------------------------

    def list_entries(self) -> List[List[str]]:
        with self._lock:
            self.memory.load()
            rows = []
            for i in range(len(self.memory)):
                key = self.memory._keys[i]  # type: ignore[attr-defined]
                exp = self.memory._experiences[i]  # type: ignore[attr-defined]
                t = self.memory._times[i]  # type: ignore[attr-defined]
                rows.append([t, key, exp])
        return rows

    def search(self, query: str, top_k: int = 5) -> List[List[str]]:
        results = self.memory.retrieve(query, top_k=top_k)
        return [[f"{r['similarity']:.3f}", r["time"], r["key"], r["experience"]] for r in results]

    def cosine_heatmap_image_path(self) -> str:
        """Render a cosine-similarity heatmap over current LTM keys."""
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        with self._lock:
            n = len(self.memory)
            if n == 0:
                emb = np.zeros((1, 1), dtype=np.float32)
            else:
                emb = self.memory._embeddings  # type: ignore[attr-defined]
                if emb is None:
                    emb = np.zeros((n, 1), dtype=np.float32)
        if emb.size == 0 or n == 0:
            sim = np.zeros((1, 1))
        else:
            norms = np.linalg.norm(emb, axis=1, keepdims=True)
            norms = np.where(norms == 0.0, 1.0, norms)
            normed = emb / norms
            sim = normed @ normed.T

        fig, ax = plt.subplots(figsize=(6, 5))
        im = ax.imshow(sim, vmin=-1.0, vmax=1.0, cmap="viridis")
        ax.set_title(f"LTM cosine similarity (n={n})")
        fig.colorbar(im, ax=ax)
        tmp = Path(tempfile.gettempdir()) / "pragmabot_ltm_heatmap.png"
        fig.tight_layout()
        fig.savefig(tmp, dpi=100)
        plt.close(fig)
        return str(tmp)

    def clear_memory(self) -> int:
        with self._lock:
            self.memory.clear()
            self.memory.save()
        return 0

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        try:
            import gradio as gr  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("gradio not installed; cannot build UI") from exc

        with gr.Blocks(title="PragmaBot LTM") as demo:
            gr.Markdown("# PragmaBot Long-Term Memory")
            count_box = gr.Number(label="Entry count", value=len(self.memory), precision=0)
            with gr.Row():
                refresh_btn = gr.Button("Refresh table")
                clear_btn = gr.Button("Clear all (irreversible)", variant="stop")
            table = gr.Dataframe(
                headers=["time", "key", "experience"],
                value=self.list_entries(),
                wrap=True,
            )

            with gr.Accordion("Search", open=True):
                query = gr.Textbox(label="Query")
                topk = gr.Slider(1, 20, value=5, step=1, label="top_k")
                search_btn = gr.Button("Search")
                results = gr.Dataframe(
                    headers=["similarity", "time", "key", "experience"], wrap=True
                )

            with gr.Accordion("Cosine similarity heatmap", open=False):
                heatmap_btn = gr.Button("Render heatmap")
                heatmap = gr.Image(label="LTM cosine similarity")

            confirm_clear = gr.Checkbox(label="I am sure — wipe LTM", value=False)

            refresh_btn.click(self.list_entries, outputs=[table])
            refresh_btn.click(lambda: len(self.memory), outputs=[count_box])
            search_btn.click(self.search, inputs=[query, topk], outputs=[results])
            heatmap_btn.click(self.cosine_heatmap_image_path, outputs=[heatmap])

            def _maybe_clear(confirmed: bool):
                if not confirmed:
                    return self.list_entries(), len(self.memory)
                self.clear_memory()
                return self.list_entries(), len(self.memory)

            clear_btn.click(
                _maybe_clear, inputs=[confirm_clear], outputs=[table, count_box]
            )

        return demo

    def run(self) -> None:
        gradio_cfg = self.cfg.get("gradio", {}) or {}
        host = str(gradio_cfg.get("host", "0.0.0.0"))
        port = int(gradio_cfg.get("port", 7862))
        share = bool(gradio_cfg.get("share", False))

        demo = self._build_ui()

        def _launch() -> None:
            demo.launch(
                server_name=host,
                server_port=port,
                share=share,
                prevent_thread_lock=True,
                show_error=True,
            )

        threading.Thread(target=_launch, name="gradio-ltm-ui", daemon=True).start()
        logger.info("Memory manager UI started at http://%s:%d", host, port)
        rospy.spin()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    node = MemoryManagerNode()
    node.run()
    return 0


if __name__ == "__main__":  # pragma: no cover - ROS entry point
    sys.exit(main())
