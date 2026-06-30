"""Grasp synthesis — pluggable backends behind a single interface."""

from .base import BaseGraspSynthesizer, GraspCandidate
from .factory import get_grasp_synthesizer
from .top_down import TopDownGraspSynthesizer

__all__ = [
    "BaseGraspSynthesizer",
    "GraspCandidate",
    "TopDownGraspSynthesizer",
    "get_grasp_synthesizer",
]
