"""Configuration loading and validation for the screening model.

The model reads its parameters from a YAML file (see ``config.yaml`` for the
defaults).  :func:`validate_config` performs a structural sanity check and
raises a clear :class:`ValueError` on problems, so misconfiguration fails
fast at startup instead of mid-simulation.
"""

from __future__ import annotations

import os

import yaml

TIDAL_SOURCES = (
    "synthetic",
    "fes2014",
    "fes",
    "tpxo9",
    "tpxo",
    "got",
    "got4.10c",
    "got4.10",
    "got410c",
)

REQUIRED_SECTIONS = (
    "domain",
    "bathymetry",
    "simulation",
    "tidal_forcing",
    "output",
    "logging",
)

_REQUIRED_KEYS = {
    "domain": ("lon_min", "lon_max", "lat_min", "lat_max"),
    "simulation": ("duration_days",),
    "output": ("dir",),
    "logging": (),
}


def default_config_path() -> str:
    """Path to the packaged default ``config.yaml``."""
    return os.path.join(os.path.dirname(__file__), "config.yaml")


def load_config(path: str | None = None) -> dict:
    """Load a YAML config file (defaults to ``config.yaml`` next to this module)."""
    if path is None:
        path = default_config_path()
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path) as f:
        config = yaml.safe_load(f)
    if not isinstance(config, dict):
        raise ValueError(f"Config file {path} must contain a YAML mapping.")
    return config


def validate_config(config: dict) -> None:
    """Raise :class:`ValueError` with a clear message if *config* is invalid."""
    for section in REQUIRED_SECTIONS:
        if section not in config:
            raise ValueError(f"Missing required config section: '{section}'")

    d = config["domain"]
    if not (d.get("lon_min", 0) < d.get("lon_max", 0)):
        raise ValueError("domain.lon_min must be < domain.lon_max")
    if not (d.get("lat_min", 0) < d.get("lat_max", 0)):
        raise ValueError("domain.lat_min must be < domain.lat_max")
    if d.get("resolution_km", 0) <= 0:
        raise ValueError("domain.resolution_km must be > 0")

    for section, keys in _REQUIRED_KEYS.items():
        for key in keys:
            if key not in config[section]:
                raise ValueError(f"Missing required key '{section}.{key}'")

    sim = config["simulation"]
    if sim.get("duration_days", 0) <= 0:
        raise ValueError("simulation.duration_days must be > 0")
    if not (0.0 < sim.get("cfl_safety", 0.5) <= 1.0):
        raise ValueError("simulation.cfl_safety must be in (0, 1]")
    if sim.get("dt") is not None and sim.get("dt") <= 0:
        raise ValueError("simulation.dt must be positive or null (auto)")

    tidal = config["tidal_forcing"]
    source = tidal.get("source", "synthetic")
    if source not in TIDAL_SOURCES:
        raise ValueError(
            f"tidal_forcing.source '{source}' not supported. "
            f"Expected one of: {', '.join(TIDAL_SOURCES)}"
        )
    if source != "synthetic" and not tidal.get("path"):
        raise ValueError(f"tidal_forcing.path is required when source is '{source}'")
    if not tidal.get("constituents"):
        raise ValueError("tidal_forcing.constituents must list at least one harmonic")

    engine = config.get("engine", {})
    if isinstance(engine, dict):
        name = engine.get("name", "python")
        if name not in ("python", "telemac2d"):
            raise ValueError(
                f"engine.name '{name}' not supported. Expected: python | telemac2d"
            )
        if name == "telemac2d" and "telemac2d" not in config:
            raise ValueError("telemac2d section is required when engine.name=telemac2d")
        if name == "telemac2d":
            telemac_cfg = config["telemac2d"]
            if not telemac_cfg.get("image"):
                raise ValueError(
                    "telemac2d.image must pin a public TELEMAC Docker image"
                )

    out = config["output"]
    if out.get("hotspot_threshold", 0) <= 0:
        raise ValueError("output.hotspot_threshold must be > 0")

    bathy = config["bathymetry"]
    if bathy.get("min_depth", 0) < 0 or bathy.get("max_depth", 0) < bathy.get(
        "min_depth", 0
    ):
        raise ValueError("bathymetry.min_depth / max_depth are inconsistent")

    # Note: a bathymetry.path that points at a missing file is NOT an error
    # here — run() logs a warning and falls back to the synthetic test grid,
    # which is the documented no-data behaviour (see README).
