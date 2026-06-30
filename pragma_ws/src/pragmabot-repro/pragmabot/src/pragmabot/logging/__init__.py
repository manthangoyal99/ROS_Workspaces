"""Per-episode structured logging.

This subpackage is named ``pragmabot.logging`` deliberately to match the
spec; it does NOT shadow the stdlib ``logging`` module because Python's
absolute imports resolve top-level ``import logging`` to the stdlib.
"""

from .episode_logger import EpisodeLogger

__all__ = ["EpisodeLogger"]
