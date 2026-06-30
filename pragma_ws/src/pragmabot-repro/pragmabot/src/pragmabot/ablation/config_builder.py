"""Cartesian-product config sweep generator."""

from __future__ import annotations

import itertools
from pathlib import Path
from typing import Any, List, Tuple, Union

from omegaconf import DictConfig, OmegaConf

from ..simple_config import load_config

PathLike = Union[str, Path]


def _flatten_for_name(key: str) -> str:
    return key.replace(".", "_")


def _format_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:g}"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


class AblationConfigBuilder:
    """Build the cartesian product of one or more parameter sweeps."""

    def __init__(self, base_config_path: PathLike) -> None:
        self._base_path = Path(base_config_path)
        self._sweeps: List[Tuple[str, List[Any]]] = []
        self._fixed: List[Tuple[str, Any]] = []

    def sweep(self, key: str, values: List[Any]) -> "AblationConfigBuilder":
        if not values:
            raise ValueError(f"sweep('{key}', ...) needs at least one value")
        self._sweeps.append((key, list(values)))
        return self

    def fix(self, key: str, value: Any) -> "AblationConfigBuilder":
        self._fixed.append((key, value))
        return self

    def __len__(self) -> int:
        n = 1
        for _, values in self._sweeps:
            n *= len(values)
        return n if self._sweeps else 1

    def build(self) -> List[Tuple[str, DictConfig]]:
        out: List[Tuple[str, DictConfig]] = []
        keys = [k for k, _ in self._sweeps]
        value_axes = [v for _, v in self._sweeps]
        combinations = list(itertools.product(*value_axes)) if value_axes else [()]
        for combo in combinations:
            cfg = load_config(self._base_path)
            # Apply fixed values first, then sweep values (sweep wins on conflict).
            for k, v in self._fixed:
                OmegaConf.update(cfg, k, v, merge=True)
            for k, v in zip(keys, combo):
                OmegaConf.update(cfg, k, v, merge=True)

            name_parts = [
                f"{_flatten_for_name(k)}={_format_value(v)}"
                for k, v in zip(keys, combo)
            ] or ["base"]
            run_name = "__".join(name_parts)
            out.append((run_name, cfg))
        return out

    def save_all(self, output_dir: PathLike) -> List[str]:
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        paths: List[str] = []
        for name, cfg in self.build():
            path = out_dir / f"{name}.yaml"
            OmegaConf.save(cfg, path)
            paths.append(str(path))
        return paths
