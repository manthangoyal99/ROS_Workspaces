"""PragmaBot main loop — full Algorithm 1 with step callbacks, timings,
typed errors, and episode logging.
"""

from __future__ import annotations

import logging as _stdlib_logging
import re
import time
from typing import Any, Callable, Dict, List, Optional

import numpy as np
from omegaconf import DictConfig

from .errors import (
    ExecutionError,
    PerceptionError,
    PlanningError,
    PragmaBotError,
    PragmaBotMemoryError,
    VLMError,
    VLMOutputParseError,
)
from .logging.episode_logger import EpisodeLogger
from .memory.embeddings import BaseEmbedder, get_embedder
from .memory.memory_manager import MemoryManager
from .memory.stm import ShortTermMemory
from .perception.annotation import ImageAnnotator
from .perception.base import BasePerception, PerceptionResult
from .perception.camera_intrinsics import farthest_point_sample
from .perception.factory import get_perception
from .planning.exp_summarizer import VLMExperienceSummarizer
from .planning.scene_describer import VLMSceneDescriber
from .planning.success_detector import VLMSuccessDetector
from .planning.task_planner import VLMTaskPlanner
from .robot.base import BaseRobot
from .robot.factory import get_robot
from .utils import get_scenario_key
from .vlm.base import BaseVLM
from .vlm.factory import get_vlm

logger = _stdlib_logging.getLogger(__name__)


_STOPWORDS = {
    "the", "a", "an", "of", "on", "in", "at", "to", "with", "and",
    "or", "for", "from", "by", "into", "onto", "is", "are", "was", "were",
    "be", "this", "that", "these", "those", "it", "its", "up", "down",
    "left", "right", "front", "back", "side", "now", "please",
    "pick", "place", "put", "push", "move", "grab", "lift", "carry",
    "set", "drop", "leave",
}


def _extract_object_queries(instruction: str, max_n: int = 6) -> List[str]:
    if not instruction:
        return []
    tokens = re.findall(r"[a-zA-Z]+", instruction.lower())
    seen: List[str] = []
    for t in tokens:
        if t in _STOPWORDS or t in seen:
            continue
        seen.append(t)
        if len(seen) >= max_n:
            break
    return seen


StepCallback = Callable[[Dict[str, Any]], None]


class PragmaBot:
    """End-to-end PragmaBot agent."""

    def __init__(
        self,
        cfg: DictConfig,
        vlm: Optional[BaseVLM] = None,
        embedder: Optional[BaseEmbedder] = None,
        memory: Optional[MemoryManager] = None,
        robot: Optional[BaseRobot] = None,
        perception: Optional[BasePerception] = None,
        step_callback: Optional[StepCallback] = None,
        episode_logger: Optional[EpisodeLogger] = None,
    ) -> None:
        self.cfg = cfg
        self.vlm = vlm if vlm is not None else get_vlm(cfg)
        self.embedder = embedder if embedder is not None else get_embedder(cfg)
        self.memory = memory if memory is not None else MemoryManager(cfg, self.embedder)
        self.robot = robot if robot is not None else get_robot(cfg)
        self.perception = perception if perception is not None else get_perception(cfg)

        self.scene_describer = VLMSceneDescriber(self.vlm, cfg)
        self.task_planner = VLMTaskPlanner(self.vlm, cfg)
        self.success_detector = VLMSuccessDetector(self.vlm, cfg)
        self.exp_summarizer = VLMExperienceSummarizer(self.vlm, cfg)
        self.annotator = ImageAnnotator()

        pipeline_cfg = cfg.get("pipeline", {})
        self.max_steps: int = int(pipeline_cfg.get("max_steps", 10))
        self.available_skills: List[str] = list(
            pipeline_cfg.get("available_skills", ["pick", "place", "push"])
        )
        self.activate_stm: bool = bool(cfg.memory.get("activate_stm", True))
        self.activate_ltm: bool = bool(cfg.memory.get("activate_ltm", True))
        self.save_to_ltm: bool = bool(cfg.memory.get("save_to_ltm", True))

        annotation_cfg = (
            cfg.perception.get("annotation") if "perception" in cfg else None
        ) or {}
        self.fps_n_candidates: int = int(annotation_cfg.get("fps_n_candidates", 5))
        self.push_n_directions: int = int(annotation_cfg.get("push_n_directions", 4))
        self.push_distance_px: int = int(annotation_cfg.get("push_distance_px", 80))

        ros_cfg = cfg.get("ros") or {}
        if bool(ros_cfg.get("rosbag_replay", False)) and self.robot.backend_name != "stub":
            raise ValueError(
                "rosbag_replay mode requires robot.backend = stub; "
                f"got {self.robot.backend_name!r}"
            )

        self.step_callback = step_callback
        log_cfg = cfg.get("logging") or {}
        self.save_episodes = bool(log_cfg.get("save_episodes", True))
        if episode_logger is not None:
            self.episode_logger: Optional[EpisodeLogger] = episode_logger
        elif self.save_episodes:
            from .utils import get_repo_root

            log_dir = str(log_cfg.get("log_dir", "pragmabot/data/logs"))
            if not log_dir.startswith("/"):
                log_dir = str(get_repo_root() / log_dir)
            self.episode_logger = EpisodeLogger(log_dir)
        else:
            self.episode_logger = None

    # ------------------------------------------------------------------
    # Callback safety
    # ------------------------------------------------------------------

    def _emit(self, payload: Dict[str, Any]) -> None:
        if self.step_callback is None:
            return
        try:
            self.step_callback(payload)
        except Exception as exc:  # pragma: no cover - callbacks must not break the loop
            logger.error("step_callback raised; swallowing: %s", exc)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_task(
        self,
        instruction: str,
        get_observation: Optional[Callable[[], np.ndarray]] = None,
        get_depth: Optional[Callable[[], Optional[np.ndarray]]] = None,
    ) -> Dict[str, Any]:
        """Run Algorithm 1 for ``instruction``.

        ``get_depth`` is optional; when provided, the depth frame is passed
        to ``perception.detect(...)`` so detected objects get a 3D centroid.
        Without it, ``centroid_3d`` is None and ``BaseRobot.execute_skill``
        has nothing to drive the EE toward.
        """
        # Clear the per-task VLM conversation log so each episode starts fresh.
        try:
            self.vlm.reset_conversation()
        except Exception:  # pragma: no cover
            pass
        observe = self._build_observation_source(get_observation)
        self._get_depth = get_depth
        # DEBUG: surface which callable is feeding the VLM. The qualname makes
        # it obvious when we accidentally fell back to ``StubRobot.get_observation``
        # (which returns black zeros) instead of a real camera source.
        try:
            _src_name = observe.__qualname__
        except AttributeError:
            _src_name = repr(observe)
        logger.info("observe source: %s", _src_name)
        queries = _extract_object_queries(instruction)
        stm = ShortTermMemory()
        scene_desc = ""
        scenario_key = ""
        ltm_entries: List[Dict[str, Any]] = []
        task_complete = False
        steps = 0
        last_annotated: Optional[np.ndarray] = None
        experience = ""
        error_message = ""

        episode_id: Optional[str] = None
        if self.episode_logger is not None:
            episode_id = self.episode_logger.start_episode(instruction, self.cfg)

        def _emit_status(phase: str, message: str, **extra: Any) -> None:
            payload: Dict[str, Any] = {
                "step": steps,
                "phase": phase,
                "action": extra.get("action"),
                "feedback": extra.get("feedback"),
                "stm_text": stm.to_text(),
                "ltm_count": len(self.memory),
                "message": message,
            }
            payload.update({k: v for k, v in extra.items() if k not in {"action", "feedback"}})
            self._emit(payload)

        try:
            # 1. scene description ------------------------------------
            try:
                initial_image = observe()
                try:
                    self.vlm.set_conversation_tag(stage="scene_describer", step=0)
                except Exception:
                    pass
                scene_desc = self.scene_describer.describe(initial_image, instruction)
            except Exception as exc:
                raise VLMError(f"scene description failed: {exc}") from exc
            _emit_status("scene_described", f"scene: {scene_desc[:80]}")

            scenario_key = get_scenario_key(instruction, scene_desc)

            # 2. LTM RAG ----------------------------------------------
            try:
                ltm_entries = (
                    self.memory.retrieve(scenario_key, top_k=self.memory.top_k)
                    if self.activate_ltm
                    else []
                )
            except Exception as exc:
                raise PragmaBotMemoryError(f"LTM retrieval failed: {exc}") from exc
            _emit_status("ltm_retrieved", f"{len(ltm_entries)} LTM entries")

            # 3. plan-execute-evaluate loop ---------------------------
            for step in range(1, self.max_steps + 1):
                steps = step
                planning_time = execution_time = detection_time = 0.0

                try:
                    before_image = observe()
                except Exception as exc:
                    logger.error("observation failed at step %d: %s", step, exc)
                    error_message = f"observation failed: {exc}"
                    break
                # DEBUG: surface the actual pixel content. Mean ≈ 0 means we
                # are sending the StubRobot zeros to the VLM.
                try:
                    _img_mean = float(np.asarray(before_image).mean())
                except Exception:  # pragma: no cover
                    _img_mean = float("nan")
                logger.info("step %d image: mean=%.1f", step, _img_mean)

                # 3a. Perception
                try:
                    t0 = time.perf_counter()
                    depth_frame = None
                    if self._get_depth is not None:
                        try:
                            depth_frame = self._get_depth()
                        except Exception as exc:
                            logger.warning("get_depth failed at step %d: %s", step, exc)
                    perception_result = self.perception.detect(
                        before_image, queries, depth=depth_frame,
                    )
                    perception_time = time.perf_counter() - t0
                except Exception as exc:
                    raise PerceptionError(f"perception failed at step {step}: {exc}") from exc

                # 3b. Planning
                t0 = time.perf_counter()
                try:
                    try:
                        self.vlm.set_conversation_tag(stage="task_planner", step=step)
                    except Exception:
                        pass
                    action = self.task_planner.plan(
                        instruction=instruction,
                        image=before_image,
                        stm=stm if self.activate_stm else ShortTermMemory(),
                        ltm_entries=ltm_entries,
                        available_skills=self.available_skills,
                        detected_objects=perception_result.objects,
                    )
                except VLMOutputParseError as exc:
                    # Soft rejection for two recoverable cases:
                    #   1. "unknown skill" — model hallucinated a skill name.
                    #   2. empty / unparseable VLM output (GPT-4o sometimes
                    #      returns "" after a few failed steps; treat as a
                    #      no-op invalid action so the next step can recover).
                    msg = str(exc)
                    if "unknown skill" in msg or "no JSON object found" in msg:
                        action = self._build_invalid_skill_action(exc)
                    else:
                        raise PlanningError(f"planning failed at step {step}: {exc}") from exc
                except Exception as exc:
                    raise PlanningError(f"planning failed at step {step}: {exc}") from exc
                planning_time = time.perf_counter() - t0
                _emit_status(
                    "planning",
                    f"planned {action.get('skill')}({action.get('parameters')})",
                    action=action,
                )

                # 3c. Annotation refinement (best-effort; never fatal).
                params = action.get("parameters", {}) or {}
                if bool(params.get("use_annotation")):
                    try:
                        annotated, action = self._refine_with_annotation(
                            instruction=instruction,
                            image=before_image,
                            stm=stm,
                            ltm_entries=ltm_entries,
                            action=action,
                            perception_result=perception_result,
                        )
                        last_annotated = annotated
                    except Exception as exc:
                        logger.warning("annotation refinement failed: %s", exc)

                # 3c'. Skill validation — reject unknown skills cheaply so the
                #      planner sees clear STM feedback on the next step instead
                #      of the robot raising ValueError (which masks the cause
                #      and tends to trigger the next VLM call to return prose).
                requested_skill = action.get("skill")
                if requested_skill not in self.available_skills:
                    action = {
                        "skill": requested_skill if isinstance(requested_skill, str) else "unknown",
                        "parameters": action.get("parameters", {}) or {},
                        "reasoning": action.get("reasoning", ""),
                        "valid": False,
                        "validation_error": (
                            f"Skill {requested_skill!r} is not available. "
                            f"Must be one of: {self.available_skills}"
                        ),
                    }
                    logger.warning(
                        "Rejecting invalid skill %r at step %d; available=%s",
                        requested_skill, step, self.available_skills,
                    )
                    _emit_status(
                        "validation_failed",
                        action["validation_error"],
                        action=action,
                    )
                    feedback = {
                        "action_success": False,
                        "task_complete": False,
                        "scene_change": (
                            f"Action rejected: skill {requested_skill!r} not available. "
                            f"Use one of: {self.available_skills}"
                        ),
                        "reasoning": action["validation_error"],
                        "executed": False,
                        "_timings": {
                            "planning_time_sec": float(planning_time),
                            "execution_time_sec": 0.0,
                            "detection_time_sec": 0.0,
                            "perception_time_sec": float(perception_time),
                        },
                    }
                    stm.append(action, feedback)
                    if self.episode_logger is not None:
                        self.episode_logger.log_step(step, action, feedback, feedback["_timings"])
                    # Move to the next planning step; the planner now sees the
                    # rejection in STM and can recover.
                    continue

                # 3d. Execution.
                # Before dispatching, if the action mentions a destination
                # name (e.g. place(target=plate)) that isn't in the current
                # perception_result, run a targeted perception call so the
                # dispatcher can resolve its 3D position.
                params = action.get("parameters", {}) or {}
                candidate_names = [
                    str(params.get(k)) for k in
                    ("object", "target", "location", "target_object", "destination", "goal")
                    if isinstance(params.get(k), str)
                ]
                missing = [n for n in candidate_names if perception_result.get_object(n) is None]
                if missing:
                    extra_queries = list({*queries, *missing})
                    try:
                        extra_result = self.perception.detect(
                            before_image, extra_queries, depth=depth_frame,
                        )
                        # Merge: keep originally-detected objects, add any new ones.
                        existing_names = {o.name.lower() for o in perception_result.objects}
                        for o in extra_result.objects:
                            if o.name.lower() not in existing_names:
                                perception_result.objects.append(o)
                        logger.info("Re-perception added: %s", missing)
                    except Exception as exc:
                        logger.warning("Re-perception for %s failed: %s", missing, exc)

                t0 = time.perf_counter()
                try:
                    executed = self.robot.execute_skill(
                        action["skill"],
                        action.get("parameters", {}),
                        perception_result=perception_result,
                    )
                except (KeyError, ValueError, TypeError) as exc:
                    logger.warning("robot rejected action %s: %s", action, exc)
                    executed = False
                except Exception as exc:
                    raise ExecutionError(
                        f"execution raised at step {step}: {exc}"
                    ) from exc
                execution_time = time.perf_counter() - t0
                _emit_status("executing", f"executed={executed}", action=action)

                # 3e. Success detection
                t0 = time.perf_counter()
                try:
                    after_image = observe()
                    try:
                        self.vlm.set_conversation_tag(stage="success_detector", step=step)
                    except Exception:
                        pass
                    feedback = self.success_detector.evaluate(
                        instruction=instruction,
                        action=action,
                        before_image=before_image,
                        after_image=after_image,
                    )
                except Exception as exc:
                    raise VLMError(
                        f"success detection failed at step {step}: {exc}"
                    ) from exc
                detection_time = time.perf_counter() - t0
                feedback = dict(feedback)
                feedback["executed"] = bool(executed)

                timings = {
                    "planning_time_sec": float(planning_time),
                    "execution_time_sec": float(execution_time),
                    "detection_time_sec": float(detection_time),
                    "perception_time_sec": float(perception_time),
                }
                # Attach timings to STM entry so they appear in the result payload.
                feedback["_timings"] = timings
                stm.append(action, feedback)

                if self.episode_logger is not None:
                    self.episode_logger.log_step(step, action, feedback, timings)

                _emit_status(
                    "evaluating",
                    f"success={feedback.get('action_success')} complete={feedback.get('task_complete')}",
                    action=action,
                    feedback=feedback,
                )

                if feedback.get("task_complete", False):
                    task_complete = True
                    break

            # 4. summarize + persist on success
            if task_complete:
                try:
                    try:
                        self.vlm.set_conversation_tag(stage="exp_summarizer", step=steps)
                    except Exception:
                        pass
                    experience = self.exp_summarizer.summarize(
                        instruction=instruction,
                        scene_description=scene_desc,
                        stm=stm,
                    )
                    if self.save_to_ltm and self.activate_ltm:
                        self.memory.store(scenario_key, experience)
                    _emit_status("storing", "experience stored in LTM")
                except Exception as exc:
                    raise PragmaBotMemoryError(
                        f"summarization/LTM store failed: {exc}"
                    ) from exc

        except PragmaBotError as exc:
            logger.error("Pipeline aborted: %s", exc)
            error_message = str(exc)
            _emit_status("error", error_message)
            task_complete = False

        # Close out the episode log (even on failure).
        log_path = ""
        conversation_log = list(getattr(self.vlm, "conversation", []) or [])
        if self.episode_logger is not None:
            try:
                log_path = self.episode_logger.end_episode(
                    success=task_complete,
                    experience=experience,
                    scenario_key=scenario_key,
                    ltm_entries_used=ltm_entries,
                    conversation=conversation_log,
                )
            except Exception as exc:  # pragma: no cover - disk failures
                logger.error("end_episode failed: %s", exc)

        return {
            "success": task_complete,
            "steps": steps,
            "stm": stm.to_list(),
            "experience": experience,
            "scenario_key": scenario_key,
            "scene_description": scene_desc,
            "ltm_entries_used": ltm_entries,
            "annotated_image_shape": (
                None if last_annotated is None else list(last_annotated.shape)
            ),
            "perception_queries": queries,
            "episode_id": episode_id,
            "episode_log_path": log_path,
            "error": error_message,
        }

    # ------------------------------------------------------------------
    # Skill-validation helper
    # ------------------------------------------------------------------

    def _build_invalid_skill_action(self, exc: VLMOutputParseError) -> Dict[str, Any]:
        """Synthesize an action dict for an unknown-skill planner failure.

        Tries to recover the original skill name and parameters from the raw
        VLM output attached to the exception so the rejection STM entry is
        as informative as possible to the next planning step.
        """
        recovered: Dict[str, Any] = {}
        raw = getattr(exc, "raw", "") or ""
        if raw:
            try:
                recovered = self.task_planner._extract_json(raw) or {}
            except Exception:
                recovered = {}

        skill = recovered.get("skill") if isinstance(recovered, dict) else None
        params = recovered.get("parameters", {}) if isinstance(recovered, dict) else {}
        reasoning = recovered.get("reasoning", "") if isinstance(recovered, dict) else ""

        return {
            "skill": skill if isinstance(skill, str) else "unknown",
            "parameters": params if isinstance(params, dict) else {},
            "reasoning": reasoning if isinstance(reasoning, str) else "",
            "valid": False,
            "validation_error": str(exc),
        }

    # ------------------------------------------------------------------
    # Annotation-refinement helper
    # ------------------------------------------------------------------

    def _refine_with_annotation(
        self,
        instruction: str,
        image: np.ndarray,
        stm: ShortTermMemory,
        ltm_entries: List[Dict[str, Any]],
        action: Dict[str, Any],
        perception_result: PerceptionResult,
    ) -> tuple[np.ndarray, Dict[str, Any]]:
        params = dict(action.get("parameters", {}))
        skill = action.get("skill", "")
        target_name = str(params.get("object", ""))
        target_obj = perception_result.get_object(target_name) if target_name else None

        candidates: List[tuple[int, int]] = []
        annotated = image.copy()
        if skill == "push":
            centroid = (
                target_obj.centroid_2d if target_obj is not None
                else (image.shape[1] // 2, image.shape[0] // 2)
            )
            candidates = self.annotator.generate_push_candidates(
                centroid,
                n_directions=self.push_n_directions,
                distance_px=self.push_distance_px,
            )
            annotated = self.annotator.annotate_candidates(image, candidates, style="circle")
        elif target_obj is not None and target_obj.mask is not None:
            ys, xs = np.nonzero(target_obj.mask)
            if xs.size > 0:
                pts = np.stack([xs, ys], axis=1)
                idx = farthest_point_sample(pts, min(self.fps_n_candidates, pts.shape[0]))
                candidates = [(int(pts[i, 0]), int(pts[i, 1])) for i in idx]
                annotated = self.annotator.annotate_candidates(image, candidates, style="circle")

        if not candidates:
            return annotated, action

        refined = self.task_planner.plan(
            instruction=(
                f"{instruction}\n[Annotated candidates: please pick a candidate "
                f"index in [1, {len(candidates)}] via parameters.candidate_index.]"
            ),
            image=annotated,
            stm=stm,
            ltm_entries=ltm_entries,
            available_skills=self.available_skills,
            detected_objects=perception_result.objects,
        )

        refined_params = dict(refined.get("parameters", {}) or {})
        idx = refined_params.get("candidate_index")
        if isinstance(idx, int) and 1 <= idx <= len(candidates):
            u, v = candidates[idx - 1]
            refined_params["candidate_pixel"] = [int(u), int(v)]
        refined["parameters"] = refined_params
        return annotated, refined

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_observation_source(
        self, get_observation: Optional[Callable[[], np.ndarray]]
    ) -> Callable[[], np.ndarray]:
        """Pick the live observation source.

        Priority (verified on Ubuntu — see experiment_log):
        1. ``get_observation`` passed explicitly to ``run_task`` always wins.
           ``StubRobot.is_connected()`` returns True, so without this we'd
           silently feed black frames to the VLM and trip the no-JSON failure.
        2. Robot's own camera, but only when the robot is connected and the
           backend isn't ``stub`` (which never returns real images).
        3. An external source previously injected via
           ``robot.set_observation_source`` (kept for backwards compatibility
           with code that wires the SceneObserver onto the robot instead of
           passing it through ``run_task``).
        4. Last resort: ``robot.get_observation`` (will be zeros for the stub
           but at least keeps the pipeline running).
        """
        # 1. Explicit external source wins.
        if get_observation is not None:
            return get_observation

        # 2. Previously-injected source on the robot itself
        #    (e.g. ``robot.set_observation_source(scene_observer.get_latest_rgb)``).
        obs_source = getattr(self.robot, "_obs_source", None)
        if callable(obs_source):
            return obs_source

        # 3. Real robot camera.
        connected = False
        try:
            connected = bool(self.robot.is_connected())
        except Exception:  # pragma: no cover
            connected = False
        robot_backend = ""
        try:
            robot_backend = str(self.cfg.robot.get("backend", "")).lower()
        except Exception:  # pragma: no cover
            robot_backend = ""
        if connected and robot_backend != "stub":
            return self.robot.get_observation

        # 4. Stub robot + REAL vlm with no observation wiring → guaranteed
        #    black images would reach a live VLM, which is the documented
        #    "no JSON found" failure cascade. Raise a clear error.
        #    Stub VLMs never look at the pixels, so we don't gate them here
        #    (preserves the existing stub-only Mac test suite).
        vlm_backend = ""
        try:
            vlm_backend = str(self.vlm.backend_name).lower()
        except Exception:  # pragma: no cover
            vlm_backend = ""
        if robot_backend == "stub" and vlm_backend not in ("stub", ""):
            raise PragmaBotError(
                "robot.backend='stub' has no observation source but "
                f"vlm.backend={vlm_backend!r} is a real VLM. Pass "
                "get_observation=... to run_task, or call "
                "robot.set_observation_source(callable) before run_task. "
                "Refusing to feed black zeros to the VLM."
            )

        # 5. Last-resort fallback (stub-VLM + stub-robot test path, or a
        #    non-stub backend that isn't connected yet).
        return self.robot.get_observation
