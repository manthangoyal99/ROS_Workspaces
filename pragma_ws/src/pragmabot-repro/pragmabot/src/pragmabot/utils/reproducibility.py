"""Reproducibility helpers — config hashing, system info, run metadata."""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import logging
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Union

from omegaconf import DictConfig, OmegaConf

logger = logging.getLogger(__name__)

PathLike = Union[str, Path]


def config_hash(cfg: DictConfig) -> str:
    """Short, stable hash over the YAML-serialised config."""
    cfg_str = OmegaConf.to_yaml(cfg, resolve=True)
    return hashlib.md5(cfg_str.encode("utf-8")).hexdigest()[:8]


def _git_commit() -> str:
    git = shutil.which("git")
    if git is None:
        return ""
    try:
        out = subprocess.check_output(
            [git, "rev-parse", "HEAD"],
            cwd=str(Path(__file__).resolve().parents[3]),
            stderr=subprocess.DEVNULL,
            timeout=2.0,
        )
        return out.decode("ascii").strip()
    except (subprocess.SubprocessError, OSError):
        return ""


def _ros_version() -> str:
    try:
        import rospy  # type: ignore  # noqa: F401
        return "noetic"
    except ImportError:
        return ""


def _torch_info() -> Dict[str, Any]:
    try:
        import torch  # type: ignore

        return {
            "version": str(getattr(torch, "__version__", "")),
            "cuda_available": bool(getattr(torch.cuda, "is_available", lambda: False)()),
        }
    except ImportError:
        return {"version": "", "cuda_available": False}


def get_system_info() -> Dict[str, Any]:
    torch_info = _torch_info()
    return {
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "torch_version": torch_info["version"],
        "cuda_available": torch_info["cuda_available"],
        "ros_version": _ros_version(),
        "pragmabot_commit": _git_commit(),
    }


def assert_backends_available(cfg: DictConfig) -> None:
    """Probe each configured backend; raise RuntimeError with a clear message on miss.

    This walks the registry rather than each factory so newly-registered
    backends are checked automatically.
    """
    from ..registry import registry

    missing: list = []
    checks = [
        ("vlm", str(cfg.vlm.get("backend", "stub"))),
        ("embedder", str(cfg.embeddings.get("backend", "stub"))),
        ("perception", str(cfg.perception.get("backend", "stub"))),
        ("robot", str(cfg.robot.get("backend", "stub"))),
    ]
    for component_type, name in checks:
        try:
            registry.get(component_type, name)
        except KeyError:
            missing.append((component_type, name))

    if missing:
        details = "\n".join(f"  - {ct}.backend={n!r}" for ct, n in missing)
        raise RuntimeError(
            "Configured backends are unavailable on this machine:\n"
            + details
            + "\nInstall the relevant dependencies or change config.yaml."
        )


def save_run_metadata(cfg: DictConfig, output_path: PathLike) -> Path:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    snapshot = OmegaConf.to_container(cfg, resolve=True)
    payload = {
        "timestamp": _dt.datetime.now().isoformat(timespec="seconds"),
        "config_hash": config_hash(cfg),
        "system_info": get_system_info(),
        "config": snapshot,
    }
    with out.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)
    return out
