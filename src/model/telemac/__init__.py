"""TELEMAC-2D refinement backend for the tidal energy assessment workflow.

This sub-package turns the fast Python screening model into a two-stage
pipeline: screen the whole archipelago, cluster the hotspots, and refine the
most energetic regions with the finite-element TELEMAC-2D solver running inside
a public Docker image.  See ``docs/engines/TELEMAC.md`` and
``docs/architecture/WORKFLOW.md``.
"""

from __future__ import annotations

from .boundaries import generate_boundaries
from .case import prepare_case
from .hotspots import cluster_hotspots, save_regions
from .mesh import (
    generate_mesh_from_grid,
    load_supplied_mesh,
    project_to_local_meters,
    unproject_from_local_meters,
)
from .postprocess import postprocess_case
from .runner import run_all, run_case
from .selafin import read_geometry, read_serafin, write_geometry
from .steering import build_steering

__all__ = [
    "generate_boundaries",
    "prepare_case",
    "cluster_hotspots",
    "save_regions",
    "generate_mesh_from_grid",
    "load_supplied_mesh",
    "project_to_local_meters",
    "unproject_from_local_meters",
    "postprocess_case",
    "run_all",
    "run_case",
    "read_geometry",
    "read_serafin",
    "write_geometry",
    "build_steering",
]
