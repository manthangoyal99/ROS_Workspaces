#!/usr/bin/env python3
"""PragmaBot ROS node — full integration of pipeline + Gradio UI + episode log.

Importable on Mac (no ROS): `PragmaBotNode()` raises a clear RuntimeError
when rospy is missing. The pipeline class itself is pure-Python; only this
node wires it to ROS topics.
"""

from __future__ import annotations

# --- ROS import guard (per CLAUDE.md) ----------------------------------------
try:
    import rospy  # type: ignore

    ROS_AVAILABLE = True
except ImportError:
    ROS_AVAILABLE = False
# -----------------------------------------------------------------------------

import logging as _stdlib_logging
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add the src directory to sys.path so this script also runs outside catkin.
_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import numpy as np  # noqa: E402

from pragmabot.logging.episode_logger import EpisodeLogger  # noqa: E402
from pragmabot.memory.embeddings import get_embedder  # noqa: E402
from pragmabot.memory.memory_manager import MemoryManager  # noqa: E402
from pragmabot.perception.factory import get_perception  # noqa: E402
from pragmabot.pipeline import PragmaBot  # noqa: E402
from pragmabot.robot.factory import get_robot  # noqa: E402
from pragmabot.simple_config import load_config  # noqa: E402
from pragmabot.utils import get_repo_root  # noqa: E402
from pragmabot.vlm.factory import get_vlm  # noqa: E402


logger = _stdlib_logging.getLogger(__name__)


def _require_ros() -> None:
    if not ROS_AVAILABLE:
        raise RuntimeError("ROS not available — pragmabot_node requires rospy.")


class PragmaBotNode:
    """Compose every PragmaBot component behind a Gradio UI."""

    def __init__(self, config_path: Optional[str] = None) -> None:
        def step(label: str) -> None:
            print(f"[INIT] {label}", flush=True)

        step("require_ros")
        _require_ros()
        step("rospy.init_node")
        if not rospy.core.is_initialized():
            rospy.init_node("pragmabot", anonymous=False)
        step("init_node done")

        if config_path is None:
            config_path = rospy.get_param(
                "~config_path", str(_SRC.parent / "config" / "config.yaml")
            )
        step(f"load_config: {config_path}")
        self._cfg = load_config(config_path)
        step("load_config done")

        # Update camera intrinsics from the live CameraInfo topic.
        try:
            from sensor_msgs.msg import CameraInfo  # type: ignore
            info_topic = self._cfg.ros.get("camera_info_topic", "/camera/color/camera_info")
            step(f"wait_for_message {info_topic}")
            info = rospy.wait_for_message(info_topic, CameraInfo, timeout=3.0)
            K = list(info.K)
            self._cfg.camera.fx = float(K[0])
            self._cfg.camera.fy = float(K[4])
            self._cfg.camera.cx = float(K[2])
            self._cfg.camera.cy = float(K[5])
            self._cfg.camera.width = int(info.width)
            self._cfg.camera.height = int(info.height)
            step(f"intrinsics ok ({self._cfg.camera.width}x{self._cfg.camera.height})")
        except Exception as exc:
            step(f"intrinsics SKIPPED: {exc}")

        step("SceneObserver")
        from pragmabot.ros.scene_observer import SceneObserver
        self._scene_observer = SceneObserver(self._cfg)
        step("get_vlm")
        self._vlm = get_vlm(self._cfg)
        step("get_embedder")
        self._embedder = get_embedder(self._cfg)
        step("MemoryManager")
        self._memory = MemoryManager(self._cfg, self._embedder)
        step("get_perception (loads Grounded SAM — slow on CPU)")
        self._perception = get_perception(self._cfg)
        step("get_robot (MoveIt init)")
        self._robot = get_robot(self._cfg)
        step("set_observation_source")
        self._robot.set_observation_source(self._scene_observer.get_latest_rgb)

        log_cfg = self._cfg.get("logging") or {}
        log_dir = str(log_cfg.get("log_dir", "pragmabot/data/logs"))
        if not log_dir.startswith("/"):
            log_dir = str(get_repo_root() / log_dir)
        step("EpisodeLogger")
        self._episode_logger = EpisodeLogger(log_dir)

        self._lock = threading.Lock()
        self._task_running = False
        self._latest_status: Dict[str, Any] = {}
        self._status_log: List[str] = []
        self._last_result: Optional[Dict[str, Any]] = None

        def _step_cb(payload: Dict[str, Any]) -> None:
            with self._lock:
                self._latest_status = dict(payload)
                msg = f"[step {payload.get('step')}/{payload.get('phase')}] {payload.get('message', '')}"
                self._status_log.append(msg)
                if len(self._status_log) > 200:
                    self._status_log = self._status_log[-200:]

        step("PragmaBot pipeline")
        self._pipeline = PragmaBot(
            cfg=self._cfg,
            vlm=self._vlm,
            embedder=self._embedder,
            memory=self._memory,
            perception=self._perception,
            robot=self._robot,
            step_callback=_step_cb,
            episode_logger=self._episode_logger,
        )
        step("PragmaBotNode ready")

    # ------------------------------------------------------------------
    # Task handling
    # ------------------------------------------------------------------

    def handle_task_request(self, instruction: str) -> Dict[str, Any]:
        instruction = (instruction or "").strip()
        if not instruction:
            return {"error": "empty instruction"}

        with self._lock:
            if self._task_running:
                return {"error": "a task is already running"}
            self._task_running = True
            self._status_log = []

        try:
            # Pass the SceneObserver explicitly so the pipeline's observation
            # source priority lands on the real ROS camera even when the
            # stub robot reports is_connected()=True. Also pass depth so
            # perception can compute 3D centroids for object localisation.
            result = self._pipeline.run_task(
                instruction,
                get_observation=self._scene_observer.get_latest_rgb,
                get_depth=self._scene_observer.get_latest_depth,
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Task crashed: %s", exc)
            result = {"error": str(exc)}
        finally:
            with self._lock:
                self._task_running = False
                self._last_result = result

        return result

    def latest_camera_frame(self) -> Optional[np.ndarray]:
        try:
            return self._scene_observer.get_latest_rgb(timeout=0.5)
        except TimeoutError:
            return None

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    @staticmethod
    def _format_stm(stm: List[Dict[str, Any]]) -> str:
        if not stm:
            return "(no steps yet)"
        lines = []
        for entry in stm:
            step = entry.get("step")
            action = entry.get("action", {})
            feedback = entry.get("feedback", {})
            lines.append(
                f"Step {step}: {action.get('skill')}({action.get('parameters')}) "
                f"-> success={feedback.get('action_success')} "
                f"complete={feedback.get('task_complete')}"
            )
        return "\n".join(lines)

    def _build_ui(self):
        try:
            import gradio as gr  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("gradio not installed; cannot build UI") from exc

        with gr.Blocks(title="PragmaBot") as demo:
            gr.Markdown("# PragmaBot")
            with gr.Row():
                with gr.Column(scale=1):
                    instruction = gr.Textbox(label="Instruction", placeholder="e.g. pick up the apple")
                    run_btn = gr.Button("Run Task", variant="primary")
                    refresh_btn = gr.Button("Refresh camera")
                    banner = gr.Markdown(value="Idle.")
                with gr.Column(scale=1):
                    camera = gr.Image(label="Latest camera frame", type="numpy")

            with gr.Row():
                current_action = gr.Textbox(label="Current action", interactive=False)
                ltm_count = gr.Number(label="LTM entries", value=len(self._memory), precision=0)
            status_log = gr.Textbox(label="Status log", lines=10, interactive=False)
            stm_box = gr.Textbox(label="Short-term memory", lines=8, interactive=False)
            result_box = gr.JSON(label="Full result")

            def _stream(text: str):
                # Kick off the task in a background thread; yield status updates from
                # self._latest_status until the task finishes.
                import time as _time

                with self._lock:
                    if self._task_running:
                        yield ("A task is already running.", "", "", "\n".join(self._status_log), {}, len(self._memory))
                        return

                worker_result: Dict[str, Any] = {}

                def _worker() -> None:
                    worker_result["result"] = self.handle_task_request(text)

                t = threading.Thread(target=_worker, name="pragmabot-task", daemon=True)
                t.start()

                while t.is_alive():
                    with self._lock:
                        snap = dict(self._latest_status)
                        log_text = "\n".join(self._status_log)
                    yield (
                        f"Running… phase={snap.get('phase', '')}",
                        str(snap.get("action") or ""),
                        self._format_stm([]),
                        log_text,
                        {},
                        len(self._memory),
                    )
                    _time.sleep(0.5)

                t.join()
                result = worker_result.get("result", {})
                summary = (
                    f"Error: {result.get('error')}" if result.get("error") else
                    f"success={result.get('success')} steps={result.get('steps')} "
                    f"episode={result.get('episode_id')}"
                )
                with self._lock:
                    log_text = "\n".join(self._status_log)
                yield (
                    summary,
                    str((result.get("stm") or [{}])[-1].get("action", "")),
                    self._format_stm(result.get("stm", [])),
                    log_text,
                    result,
                    len(self._memory),
                )

            run_btn.click(
                _stream,
                inputs=[instruction],
                outputs=[banner, current_action, stm_box, status_log, result_box, ltm_count],
            )
            refresh_btn.click(
                lambda: self.latest_camera_frame(),
                inputs=None,
                outputs=[camera],
            )

            # ---------- Conversation log tab ----------
            with gr.Accordion("VLM conversation log (latest episode)", open=False):
                conv_refresh = gr.Button("Load latest episode")
                conv_view = gr.HTML(value="<i>Run a task, then click Load.</i>")
                conv_refresh.click(self._render_latest_conversation, outputs=[conv_view])

        return demo

    # ------------------------------------------------------------------
    # Conversation log rendering
    # ------------------------------------------------------------------

    def _render_latest_conversation(self) -> str:
        """Read the most recent episode JSON and render its VLM conversation as HTML."""
        import glob
        import html as _html
        import json as _json
        import os

        log_dir = str(self._episode_logger.log_dir)
        files = sorted(
            glob.glob(os.path.join(log_dir, "episode_*.json")),
            key=os.path.getmtime,
        )
        if not files:
            return "<i>No episodes found.</i>"
        try:
            with open(files[-1], "r", encoding="utf-8") as f:
                ep = _json.load(f)
        except Exception as exc:
            return f"<pre>Failed to read {files[-1]}: {_html.escape(str(exc))}</pre>"

        conv = ep.get("conversation") or []
        if not conv:
            return f"<i>No conversation recorded for episode {ep.get('episode_id', '?')}.</i>"

        parts = [
            f"<h3>Episode {_html.escape(str(ep.get('episode_id', '?')))} — "
            f"instruction: {_html.escape(str(ep.get('instruction', '')))}</h3>"
        ]
        for i, entry in enumerate(conv, start=1):
            stage = entry.get("stage") or "?"
            step = entry.get("step")
            parts.append("<hr/>")
            parts.append(
                f"<h4>#{i} &middot; stage: <code>{_html.escape(str(stage))}</code> "
                f"&middot; step: <code>{step}</code></h4>"
            )
            # Images (already PNG-base64 thumbnails)
            for b64 in (entry.get("images_b64") or []):
                if isinstance(b64, str) and b64:
                    parts.append(
                        f'<img src="data:image/png;base64,{b64}" '
                        f'style="max-width:320px;border:1px solid #ccc;margin:4px;"/>'
                    )
            # Messages
            parts.append("<details open><summary><b>Prompt</b></summary>")
            for m in (entry.get("messages") or []):
                role = _html.escape(str(m.get("role", "user")))
                content = m.get("content", "")
                if isinstance(content, list):
                    content = " ".join(
                        str(p.get("text", "")) for p in content if isinstance(p, dict)
                    )
                parts.append(
                    f"<div style='margin:6px 0;'><b>{role}:</b><pre style='white-space:pre-wrap;"
                    f"background:#f6f8fa;padding:8px;border-radius:4px;'>"
                    f"{_html.escape(str(content))}</pre></div>"
                )
            parts.append("</details>")
            # Response
            parts.append(
                "<details open><summary><b>VLM response</b></summary>"
                f"<pre style='white-space:pre-wrap;background:#eef9ee;padding:8px;"
                f"border-radius:4px;'>{_html.escape(str(entry.get('response', '')))}</pre>"
                "</details>"
            )
        return "\n".join(parts)

    def run(self) -> None:
        gradio_cfg = self._cfg.get("gradio") or {}
        host = str(gradio_cfg.get("host", "0.0.0.0"))
        port = int(gradio_cfg.get("port", 7861))
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

        threading.Thread(target=_launch, name="gradio-ui", daemon=True).start()
        logger.info("Gradio UI started at http://%s:%d", host, port)
        rospy.spin()


def main() -> int:
    _stdlib_logging.basicConfig(level=_stdlib_logging.INFO,
                                format="%(levelname)s %(name)s %(message)s")
    PragmaBotNode().run()
    return 0


if __name__ == "__main__":  # pragma: no cover - ROS entry point
    sys.exit(main())
