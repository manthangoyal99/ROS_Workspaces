"""OmegaConf-based YAML configuration loader."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Union

from omegaconf import DictConfig, OmegaConf

logger = logging.getLogger(__name__)

PathLike = Union[str, Path]


def load_config(path: PathLike) -> DictConfig:
    """Load a YAML configuration file into an OmegaConf DictConfig.

    If a file named ``config_local.yaml`` exists in the same directory as
    ``path``, it is merged on top of the base config (local overrides win).
    The local file is not required to be a complete config — any subset of
    keys is sufficient.

    Args:
        path: Path to a YAML config file.

    Returns:
        Parsed configuration as a DictConfig.

    Raises:
        FileNotFoundError: If the base config file does not exist.
        TypeError: If the YAML root is not a mapping.
    """
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found at: {config_path}")

    cfg = OmegaConf.load(config_path)
    if not isinstance(cfg, DictConfig):
        raise TypeError(f"Expected a mapping at config root, got: {type(cfg).__name__}")

    logger.info("Configuration loaded from: %s", config_path)

    local_path = config_path.parent / "config_local.yaml"
    if local_path.exists():
        local_cfg = OmegaConf.load(local_path)
        if not isinstance(local_cfg, DictConfig):
            raise TypeError(
                f"Expected a mapping at config_local.yaml root, got: {type(local_cfg).__name__}"
            )
        cfg = OmegaConf.merge(cfg, local_cfg)
        if not isinstance(cfg, DictConfig):  # pragma: no cover - OmegaConf invariant
            raise TypeError("Merged config is not a DictConfig.")
        logger.info("Merged local config from: %s", local_path)

    return cfg


def save_config(cfg: DictConfig, path: PathLike) -> None:
    """Persist a DictConfig to a YAML file.

    Args:
        cfg: The configuration object to save.
        path: Destination YAML path.
    """
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    OmegaConf.save(cfg, out)
    logger.info("Configuration saved to: %s", out)


def merge_configs(base: DictConfig, override: dict) -> DictConfig:
    """Merge an override mapping on top of a base configuration.

    Args:
        base: Base configuration.
        override: Dict-like override (will be converted via OmegaConf).

    Returns:
        A new merged DictConfig (base is not mutated).
    """
    override_cfg = OmegaConf.create(override)
    merged = OmegaConf.merge(base, override_cfg)
    if not isinstance(merged, DictConfig):
        raise TypeError("Merged config is not a DictConfig.")
    return merged
