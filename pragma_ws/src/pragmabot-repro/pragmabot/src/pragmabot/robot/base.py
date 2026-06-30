"""Abstract robot interface.

Files that import ROS must guard imports per CLAUDE.md, but this base file
contains no ROS imports and is safe on Mac.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, Optional

import numpy as np

VALID_SKILLS = ("pick", "place", "push")

# Type alias for an observation source: a callable returning an HxWx3 uint8 array.
ObservationSource = Callable[[], np.ndarray]


class BaseRobot(ABC):
    """Abstract robot backend.

    Each ``execute_*`` returns True if the call was *attempted* without an
    immediate error — observed success/failure is decided downstream by the
    VLM success detector by comparing before/after images.

    Subclasses may override :meth:`get_observation` to capture images from
    their native camera. To inject an external observation source (e.g., a
    ROS topic in rosbag-replay mode) call :meth:`set_observation_source`;
    after that, :meth:`get_observation` returns whatever the injected
    callable produces.
    """

    # Set via ``set_observation_source``. None means "use the native source".
    _obs_source: Optional[ObservationSource] = None

    @abstractmethod
    def execute_pick(
        self,
        object_name: str,
        target_position_3d: Optional[np.ndarray] = None,
        location_hint: Optional[str] = None,
    ) -> bool:
        """Pick up the named object, optionally at a known 3D position."""

    @abstractmethod
    def execute_place(
        self,
        object_name: str,
        target_position_3d: Optional[np.ndarray] = None,
        location: Optional[str] = None,
    ) -> bool:
        """Place a held object at a 3D position and/or named location."""

    @abstractmethod
    def execute_push(
        self,
        object_name: str,
        goal_position_3d: Optional[np.ndarray] = None,
        direction: Optional[str] = None,
    ) -> bool:
        """Push the named object toward a 3D goal and/or in a named direction."""

    def get_observation(self) -> np.ndarray:
        """Return the current RGB image as an HxWx3 uint8 array.

        Default implementation: if an external observation source has been
        injected via :meth:`set_observation_source`, return its output;
        otherwise dispatch to :meth:`_native_observation`.
        """
        if self._obs_source is not None:
            obs = self._obs_source()
            if not isinstance(obs, np.ndarray):
                raise TypeError(
                    f"observation source returned {type(obs).__name__}, expected np.ndarray"
                )
            return obs
        return self._native_observation()

    @abstractmethod
    def _native_observation(self) -> np.ndarray:
        """Backend-native observation (called when no source is injected)."""

    def set_observation_source(self, source: Optional[ObservationSource]) -> None:
        """Override the robot's internal camera with an external callable.

        Pass ``None`` to clear the override and resume using the native source.
        """
        if source is not None and not callable(source):
            raise TypeError("observation source must be callable or None")
        self._obs_source = source

    def has_observation_source(self) -> bool:
        """True if an external observation source has been injected."""
        return self._obs_source is not None

    @abstractmethod
    def is_connected(self) -> bool:
        """True if the underlying robot hardware is reachable."""

    @property
    @abstractmethod
    def backend_name(self) -> str:
        """Short identifier of the backend."""

    # ------------------------------------------------------------------
    # Convenience dispatcher
    # ------------------------------------------------------------------

    def execute_skill(
        self,
        skill: str,
        parameters: Dict[str, Any],
        perception_result: Optional[Any] = None,
    ) -> bool:
        """Dispatch to the matching ``execute_*`` method.

        Args:
            skill: One of ``"pick"``, ``"place"``, ``"push"``.
            parameters: Skill-specific parameters dict. May include
                ``target_position_3d`` / ``goal_position_3d`` (np.ndarray) to
                bypass perception lookup, or ``object`` to look up via
                ``perception_result``.
            perception_result: Optional ``PerceptionResult`` providing 3D
                centroids for named objects. Used as a fallback target
                position when ``parameters`` does not specify one.

        Raises:
            ValueError: If ``skill`` is not recognised.
            KeyError: If a required parameter is missing.
        """
        if not isinstance(parameters, dict):
            raise TypeError(f"parameters must be dict, got {type(parameters).__name__}")
        skill = (skill or "").lower()

        def _coerce_xyz(value: Any) -> Optional[np.ndarray]:
            if value is None:
                return None
            arr = np.asarray(value, dtype=float).reshape(-1)
            if arr.size != 3:
                raise ValueError(f"3D position must have 3 elements, got {arr.shape}")
            return arr

        target_3d = _coerce_xyz(
            parameters.get("target_position_3d") or parameters.get("goal_position_3d")
        )

        def _name_from(*keys: str) -> Optional[str]:
            """Pick the first string-valued parameter from ``keys``."""
            for k in keys:
                v = parameters.get(k)
                if isinstance(v, str) and v:
                    return v
            return None

        # The planner is inconsistent about parameter names; we accept the
        # full set of synonyms we've observed it produce.
        if skill == "pick":
            obj_name = _name_from("object", "target", "target_object", "name", "item")
            if obj_name is None:
                raise KeyError("pick requires an object name (object/target/...)")
            if target_3d is None and perception_result is not None:
                o = perception_result.get_object(obj_name)
                if o is not None and o.centroid_3d is not None:
                    target_3d = np.asarray(o.centroid_3d, dtype=float)
            return self.execute_pick(
                object_name=obj_name,
                target_position_3d=target_3d,
                location_hint=parameters.get("location_hint"),
            )

        if skill == "place":
            held = _name_from("object", "item")
            dest_name = _name_from(
                "location", "target", "target_object", "destination", "goal", "on",
            )
            if target_3d is None and perception_result is not None and dest_name:
                o = perception_result.get_object(dest_name)
                if o is not None and o.centroid_3d is not None:
                    target_3d = np.asarray(o.centroid_3d, dtype=float)
            return self.execute_place(
                object_name=held or "(held)",
                target_position_3d=target_3d,
                location=dest_name,
            )

        if skill == "push":
            obj_name = _name_from("object", "target", "target_object", "name", "item")
            if target_3d is None and perception_result is not None and obj_name:
                o = perception_result.get_object(obj_name)
                if o is not None and o.centroid_3d is not None:
                    target_3d = np.asarray(o.centroid_3d, dtype=float)
            return self.execute_push(
                object_name=obj_name or "",
                goal_position_3d=target_3d,
                direction=parameters.get("direction"),
            )

        raise ValueError(f"Unknown skill: {skill!r}; expected one of {VALID_SKILLS}")
