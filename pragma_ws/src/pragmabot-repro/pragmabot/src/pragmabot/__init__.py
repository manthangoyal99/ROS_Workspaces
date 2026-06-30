"""PragmaBot reproduction — pure-Python core library."""

__version__ = "0.1.0"

# Importing the registry triggers ``_register_defaults`` which wires every
# built-in backend into the shared ``ComponentRegistry``. Factories rely on
# this side-effect; doing it at package import time guarantees registrations
# are in place before anyone calls ``get_vlm``/``get_perception``/etc.
from . import registry as _registry  # noqa: F401  (side-effect: registrations)
