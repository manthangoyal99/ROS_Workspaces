"""Component registry — every pluggable backend lives here.

Register a new backend in one line via the ``@registry.register`` decorator,
then select it from ``config.yaml``. Existing factory functions delegate to
``registry.get`` so adding a backend never requires touching another file.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Type

logger = logging.getLogger(__name__)


class ComponentRegistry:
    """Central (component_type, backend_name) → class map."""

    def __init__(self) -> None:
        self._registry: Dict[str, Dict[str, Type]] = {}

    # ------------------------------------------------------------------

    def register(self, component_type: str, name: str) -> Callable[[Type], Type]:
        """Decorator: register ``cls`` under ``(component_type, name)``.

        Re-registering the same (type, name) replaces the previous class
        and logs a debug message — useful for monkeypatching in tests.
        """

        def _decorator(cls: Type) -> Type:
            bucket = self._registry.setdefault(component_type, {})
            if name in bucket and bucket[name] is not cls:
                logger.debug(
                    "Re-registering %s/%s: %s → %s",
                    component_type, name, bucket[name].__name__, cls.__name__,
                )
            bucket[name] = cls
            return cls

        return _decorator

    def get(self, component_type: str, name: str) -> Type:
        """Look up a registered class, raising a helpful KeyError on miss."""
        bucket = self._registry.get(component_type, {})
        if name not in bucket:
            available = sorted(bucket.keys())
            raise KeyError(
                f"No backend {name!r} registered for component_type "
                f"{component_type!r}. Available: {available or '(none)'}"
            )
        return bucket[name]

    def list_available(self, component_type: str) -> List[str]:
        return sorted(self._registry.get(component_type, {}).keys())

    def list_component_types(self) -> List[str]:
        return sorted(self._registry.keys())

    def instantiate(self, component_type: str, name: str, *args: Any, **kwargs: Any) -> Any:
        cls = self.get(component_type, name)
        return cls(*args, **kwargs)


# Global singleton.
registry = ComponentRegistry()


def _register_defaults() -> None:
    """Register all built-in backends at import time."""
    # VLM ---------------------------------------------------------------
    from pragmabot.vlm.stub_vlm import StubVLM
    registry.register("vlm", "stub")(StubVLM)
    try:
        from pragmabot.vlm.ollama_vlm import OllamaVLM
        registry.register("vlm", "ollama")(OllamaVLM)
    except Exception as exc:  # pragma: no cover - optional dep failure
        logger.debug("Ollama VLM unavailable: %s", exc)
    try:
        from pragmabot.vlm.openai_vlm import OpenAIVLM
        registry.register("vlm", "openai")(OpenAIVLM)
    except Exception as exc:  # pragma: no cover
        logger.debug("OpenAI VLM unavailable: %s", exc)

    # Embedders ---------------------------------------------------------
    from pragmabot.memory.embeddings import OpenAIEmbedder, StubEmbedder
    registry.register("embedder", "stub")(StubEmbedder)
    registry.register("embedder", "openai")(OpenAIEmbedder)
    try:
        from pragmabot.memory.embeddings import SentenceTransformerEmbedder
        registry.register("embedder", "sentence_transformers")(SentenceTransformerEmbedder)
    except Exception as exc:  # pragma: no cover - heavy dep
        logger.debug("SentenceTransformer embedder unavailable: %s", exc)

    # Perception --------------------------------------------------------
    from pragmabot.perception.stub_perception import StubPerception
    registry.register("perception", "stub")(StubPerception)
    try:
        from pragmabot.perception.grounded_sam import GroundedSAMPerception
        registry.register("perception", "grounded_sam")(GroundedSAMPerception)
    except Exception as exc:  # pragma: no cover
        logger.debug("GroundedSAM perception unavailable: %s", exc)

    # Robot -------------------------------------------------------------
    from pragmabot.robot.stub_robot import StubRobot
    registry.register("robot", "stub")(StubRobot)
    try:
        from pragmabot.robot.franka_ros import FrankaRobot, ROS_AVAILABLE
        if ROS_AVAILABLE:
            registry.register("robot", "franka_ros")(FrankaRobot)
        else:
            logger.debug("FrankaRobot module loaded but ROS unavailable; not registered.")
    except Exception as exc:  # pragma: no cover
        logger.debug("FrankaRobot unavailable: %s", exc)

    # Grasp -------------------------------------------------------------
    from pragmabot.robot.grasp.top_down import TopDownGraspSynthesizer
    registry.register("grasp", "top_down")(TopDownGraspSynthesizer)

    # Baselines — module import side-effects register cap_v / come.
    try:
        from pragmabot import baselines as _baselines  # noqa: F401
    except Exception as exc:  # pragma: no cover
        logger.debug("baselines unavailable: %s", exc)


_register_defaults()
