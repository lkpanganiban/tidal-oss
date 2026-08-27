"""Assemble a complete TELEMAC-2D case directory for one refinement region.

A case directory contains:

* ``mesh.slf`` -- geometry (written by :mod:`model.telemac.mesh`)
* ``mesh.cli`` / ``mesh.liq`` -- boundary conditions (written by
  :mod:`model.telemac.boundaries`)
* ``case.cas`` -- steering file (written by :mod:`model.telemac.steering`)
* ``manifest.json`` -- provenance + projection metadata consumed by the
  post-processor and by the Docker runner.

The case is self-contained: the Docker runner only needs to mount the case
directory and invoke ``telemac2d.py case.cas`` inside the public TELEMAC image.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

import numpy as np

from .boundaries import generate_boundaries
from .hotspots import HotspotRegion
from .mesh import (
    RefinementMesh,
    generate_mesh_from_grid,
    load_supplied_mesh,
    save_manifest,
)
from .steering import build_steering


@dataclass
class PreparedCase:
    case_dir: str
    mesh: RefinementMesh
    manifest_path: str


def compute_times(duration_days: float, time_step: float) -> tuple[np.ndarray, int]:
    duration = float(duration_days) * 86400.0
    n_steps = int(round(duration / time_step))
    times = np.arange(n_steps + 1) * time_step
    return times, n_steps


def prepare_case(
    region: HotspotRegion,
    config: dict,
    tidal: dict,
    cases_dir: str,
    *,
    grid=None,
    supplied_mesh: dict | None = None,
) -> PreparedCase:
    """Build all files for a single refinement case and return its directory."""
    telemac_cfg = config.get("telemac2d", {})
    mesh_cfg = telemac_cfg.get("mesh", {})
    steering_cfg = telemac_cfg.get("steering", {})

    case_dir = os.path.join(cases_dir, region.id)
    os.makedirs(case_dir, exist_ok=True)

    mesh_source = mesh_cfg.get("source", "generated")
    if mesh_source == "supplied":
        if supplied_mesh is None:
            raise ValueError(
                "telemac2d.mesh.supplied_mesh is required for source='supplied'"
            )
        mesh = load_supplied_mesh(
            supplied_mesh["path"],
            bbox=region.bbox,
            coordinates_are_meters=supplied_mesh.get("coordinates_are_meters", True),
            lon0=supplied_mesh.get("lon0", 0.0),
            lat0=supplied_mesh.get("lat0", 0.0),
        )
    elif mesh_source == "generated":
        if grid is None:
            raise ValueError(
                "a screening StructuredGrid is required to generate a mesh"
            )
        mesh = generate_mesh_from_grid(
            grid,
            region.bbox,
            os.path.join(case_dir, "mesh.slf"),
            edge_types=mesh_cfg.get("boundary", {}).get("edge_types"),
            land_shapefile=config.get("bathymetry", {}).get("land_shapefile"),
        )
    else:
        raise ValueError(f"unknown telemac2d.mesh.source: {mesh_source}")

    save_manifest(mesh, os.path.join(case_dir, "mesh_manifest.json"))

    time_step = float(
        steering_cfg.get("time_step", config.get("simulation", {}).get("dt") or 30.0)
    )
    duration_days = float(
        steering_cfg.get(
            "duration_days", config.get("simulation", {}).get("duration_days", 15)
        )
    )
    times, n_steps = compute_times(duration_days, time_step)

    boundaries = generate_boundaries(
        mesh,
        mesh_cfg,
        tidal,
        times,
        case_dir,
        edge_types=mesh_cfg.get("boundary", {}).get("edge_types"),
        liquid_nodes_file=mesh_cfg.get("boundary", {}).get("liquid_nodes_file"),
    )

    build_steering(
        case_dir, time_step, n_steps, telemac_cfg, title=f"TIDAL-OSS {region.id}"
    )

    manifest = {
        "engine": "telemac2d",
        "region_id": region.id,
        "bbox": region.bbox,
        "max_power_Wm2": region.max_power,
        "image": telemac_cfg.get("image", "flussplan/telemac:v8-latest"),
        "ncsize": int(telemac_cfg.get("ncsize", 1)),
        "time_step": time_step,
        "duration_days": duration_days,
        "n_steps": n_steps,
        "mesh_path": mesh.path,
        "cli_path": boundaries.cli_path,
        "liq_path": boundaries.liq_path,
        "n_boundary_points": boundaries.n_boundary_points,
        "n_liquid_points": len(boundaries.liquid_point_order),
        "n_liquid_boundaries": boundaries.n_segments,
        "nliq": boundaries.nliq,
        "lon0": mesh.lon0,
        "lat0": mesh.lat0,
        "coordinates_are_meters": mesh.coordinates_are_meters,
        "tidal_source": tidal.get("source", "synthetic"),
        "constituents": tidal.get("constituents", []),
    }
    manifest_path = os.path.join(case_dir, "manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    return PreparedCase(case_dir=case_dir, mesh=mesh, manifest_path=manifest_path)
