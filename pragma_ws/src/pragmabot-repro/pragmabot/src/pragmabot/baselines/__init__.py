"""Baseline planners — alternate planners that can be swapped into the eval loop.

Importing this package registers ``cap_v`` and ``come`` under the global
component registry's ``"baseline"`` type.
"""

from .base import BaseBaseline
from .cap_v import CaPVBaseline
from .come import COMEBaseline
from .factory import get_baseline

__all__ = ["BaseBaseline", "CaPVBaseline", "COMEBaseline", "get_baseline"]
