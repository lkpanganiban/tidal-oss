"""Build TELEMAC boundary-condition (``.cli``) and liquid-boundary (``.liq``) files.

Open (liquid) boundaries carry the tidal elevation reconstructed from the same
harmonic constituents used by the screening model, so the refinement is
one-way nested in the parent run.  Solid (coast/land) boundaries are treated as
no-flux walls via ``LIEBOR=2``.

Boundary points are processed in TELEMAC's own ordering: the k-th line of the
``.cli`` file corresponds to the mesh node whose ``IPOBO`` value equals ``k``.
The same ordering is used for the liquid-boundary time series in the ``.liq``
file, which lists only the liquid boundary points and only the prescribed
variables (default: elevation, ``NLIQ=1``).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field

import numpy as np

from .mesh import RefinementMesh

LIQUID_ELEVATION = 5
SOLID_WALL = 2
FREE = 4

TOL_DEG = 1.0e-6


@dataclass
class BoundarySet:
    """Paths and ordering produced for one refinement case."""

    cli_path: str
    liq_path: str
    n_boundary_points: int
    liquid_point_order: list[int] = field(default_factory=list)
    liquid_node_global: list[int] = field(default_factory=list)
    nliq: int = 1
    n_segments: int = 1


def _edge_of_node(lon: float, lat: float, bbox: dict) -> str:
    if lon <= bbox["lon_min"] + TOL_DEG:
        return "left"
    if lon >= bbox["lon_max"] - TOL_DEG:
        return "right"
    if lat <= bbox["lat_min"] + TOL_DEG:
        return "bottom"
    if lat >= bbox["lat_max"] - TOL_DEG:
        return "top"
    return "interior"


def classify_boundary_points(
    mesh: RefinementMesh, edge_types: dict[str, str]
) -> list[bool]:
    """Return, for each boundary point in IPOBO order, whether it is liquid.

    Edge classification uses the mesh's *own* node extents, not the cluster
    bounding box: for generated meshes the nodes are screening-grid cell
    centres, which sit inside the cluster ``bbox`` (so comparing against that
    box would misclassify every boundary point as interior → solid).
    """
    geom = mesh.geometry
    ipobo = geom.ipobo
    nbnd = int((ipobo > 0).sum())
    edge_bbox = {
        "lon_min": float(mesh.node_lon.min()),
        "lon_max": float(mesh.node_lon.max()),
        "lat_min": float(mesh.node_lat.min()),
        "lat_max": float(mesh.node_lat.max()),
    }
    is_liquid = []
    for k in range(1, nbnd + 1):
        node = int(np.where(ipobo == k)[0][0])
        lon = float(mesh.node_lon[node])
        lat = float(mesh.node_lat[node])
        edge = _edge_of_node(lon, lat, edge_bbox)
        kind = edge_types.get(edge, "solid")
        is_liquid.append(kind == "liquid")
    return is_liquid


def write_cli(mesh: RefinementMesh, is_liquid: list[bool], path: str) -> None:
    """Write the TELEMAC ``.cli`` boundary-conditions file.

    TELEMAC v7/v8 expects 13 whitespace-separated columns per boundary point
    (in IPOBO order)::

        LIEBOR LIUBOR LIVBOR 0.0 0.0 0.0 0.0 LITBOR 0.0 0.0 0.0 NODE IPOBO

    where ``NODE`` is the global (1-based) mesh-node index of the point and
    ``IPOBO`` is the 1-based boundary-point counter.  ``LIEBOR=5`` marks a
    liquid (prescribed-elevation) point; ``LIEBOR=2`` a solid wall.
    """
    geom = mesh.geometry
    ipobo = geom.ipobo
    nbnd = int((ipobo > 0).sum())
    lines = []
    for k in range(1, nbnd + 1):
        node = int(np.where(ipobo == k)[0][0]) + 1  # 1-based global node
        if is_liquid[k - 1]:
            liebor, liubor, livbor, litbor = LIQUID_ELEVATION, FREE, FREE, FREE
        else:
            liebor, liubor, livbor, litbor = (
                SOLID_WALL,
                SOLID_WALL,
                SOLID_WALL,
                SOLID_WALL,
            )
        lines.append(
            f"{liebor:>5d}{liubor:>5d}{livbor:>5d}"
            f"{0.0:11.3f}{0.0:11.3f}{0.0:11.3f}{0.0:11.3f}"
            f"{litbor:>5d}"
            f"{0.0:11.3f}{0.0:11.3f}{0.0:11.3f}"
            f"{node:>11d}{k:>11d}"
        )
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def write_liq(
    times: np.ndarray, liquid_series: np.ndarray, path: str, nliq: int | None = None
) -> None:
    """Write the TELEMAC ``.liq`` liquid-boundary time series.

    TELEMAC v7/v8 reads this file with ``READ_FIC_FRLIQ`` and expects one column
    per **liquid boundary** (``SL(1)`` for boundary 1, ``SL(2)`` for boundary 2,
    ...).  ``NUMLIQ`` is determined by the boundary-conditions file, and TELEMAC
    reads exactly that many ``SL(i)`` columns; any extra columns are ignored.
    Each column is the (uniform-along-the-boundary) prescribed elevation time
    series for one liquid boundary segment.

    ``liquid_series`` has shape ``(nt, nliq)`` — one column per liquid boundary.
    """
    times = np.asarray(times, dtype=np.float64)
    liquid_series = np.asarray(liquid_series, dtype=np.float64)
    if liquid_series.ndim == 3:
        # Backwards-compatible: collapse the (nt, nliq, n_liquid) form.
        liquid_series = liquid_series[:, 0, :]
    nt, ncols = liquid_series.shape
    if nliq is None:
        nliq = ncols

    header = ["T"] + [f"SL({i})" for i in range(1, nliq + 1)]
    units = ["s"] + ["m"] * nliq
    with open(path, "w") as f:
        f.write(" ".join(header) + "\n")
        f.write(" ".join(units) + "\n")
        for t_idx in range(nt):
            parts = [f"{times[t_idx]:.3f}"]
            parts.extend(f"{val:.6e}" for val in liquid_series[t_idx, :nliq])
            f.write(" ".join(parts) + "\n")


def _phase_lag_seconds(
    rep_lon: float,
    rep_lat: float,
    ref_lon: float,
    ref_lat: float,
    config: dict,
) -> float:
    """Phase lag [s] to impose a propagating tide at ``(rep_lon, rep_lat)``.

    A box far smaller than the tidal wavelength that is forced in-phase on every
    boundary only sustains a standing wave (velocity node at the centre,
    antinodes at the edges).  Real tides *propagate*: the signal arrives at one
    boundary before the opposite one, driving through-flow.  GOT's own phase
    gradient over a sub-domain of a few tenths of a degree is only a few degrees,
    so we optionally impose a linear phase lag proportional to distance along
    the propagation direction.

    Configure under ``telemac2d.mesh.boundary``:

    * ``phase_speed_mps`` -- tidal phase speed [m/s].  When set, the phase is
      retarded by ``omega * distance / phase_speed`` from the reference
      (westernmost / southernmost) point.  ``null`` (default) applies no offset.
    * ``propagation_axis`` -- ``'lon'`` (default) or ``'lat'``: the direction
      the wave travels.

    ``config`` here is the ``telemac2d.mesh`` mapping.
    """
    boundary_cfg = config.get("boundary", {}) if isinstance(config, dict) else {}
    phase_speed = boundary_cfg.get("phase_speed_mps")
    if not phase_speed:
        return 0.0
    axis = boundary_cfg.get("propagation_axis", "lon")
    if axis == "lon":
        metres_per_deg = 111320.0 * math.cos(math.radians(rep_lat))
        dist = (rep_lon - ref_lon) * metres_per_deg
    else:
        metres_per_deg = 110540.0
        dist = (rep_lat - ref_lat) * metres_per_deg
    return float(dist) / float(phase_speed)


def _group_segments(is_liquid: list[bool]) -> list[list[int]]:
    """Group liquid boundary indices (in IPOBO order) into contiguous segments."""
    segments: list[list[int]] = []
    current: list[int] = []
    for k in range(1, len(is_liquid) + 1):
        if is_liquid[k - 1]:
            if current and k != current[-1] + 1:
                segments.append(current)
                current = []
            current.append(k)
    if current:
        segments.append(current)
    return segments


def generate_boundaries(
    mesh: RefinementMesh,
    config: dict,
    tidal: dict,
    times: np.ndarray,
    cas_dir: str,
    *,
    edge_types: dict[str, str] | None = None,
    liquid_nodes_file: str | None = None,
) -> BoundarySet:
    """Create ``.cli`` and ``.liq`` for a refinement mesh.

    The liquid boundary points are grouped into contiguous segments (separated
    by solid walls).  TELEMAC treats each segment as one liquid boundary and
    prescribes a *uniform* elevation along it, so we emit one ``.liq`` column per
    segment: ``SL(1)`` for the first segment, ``SL(2)`` for the second, etc.
    Imposing a different phase on each segment (see :func:`_phase_lag_seconds`)
    is what drives through-flow instead of a standing wave.
    """
    from model.forcing import build_tidal_boundary, read_tidal_constituents

    if edge_types is None:
        edge_types = config.get("boundary", {}).get(
            "edge_types",
            {"left": "liquid", "right": "liquid", "top": "solid", "bottom": "solid"},
        )

    geom = mesh.geometry
    ipobo = geom.ipobo
    nbnd = int((ipobo > 0).sum())

    if liquid_nodes_file:
        with open(liquid_nodes_file) as f:
            liquid_points = set(int(x) for x in json.load(f))
        is_liquid = [k in liquid_points for k in range(1, nbnd + 1)]
    elif mesh.liquid_ipobo is not None:
        liquid_points = set(int(x) for x in mesh.liquid_ipobo)
        is_liquid = [k in liquid_points for k in range(1, nbnd + 1)]
    else:
        is_liquid = classify_boundary_points(mesh, edge_types)

    cli_path = f"{cas_dir}/mesh.cli"
    liq_path = f"{cas_dir}/mesh.liq"
    write_cli(mesh, is_liquid, cli_path)

    liquid_point_order = [k for k in range(1, nbnd + 1) if is_liquid[k - 1]]
    liquid_node_global = [int(np.where(ipobo == k)[0][0]) for k in liquid_point_order]

    segments = _group_segments(is_liquid)
    n_segments = len(segments)

    if segments:
        # Representative (mean) location of each liquid-boundary segment, plus the
        # reference point (westernmost / southernmost) for the imposed phase lag.
        seg_lon: list[float] = []
        seg_lat: list[float] = []
        for seg in segments:
            idx_in_order = [liquid_point_order.index(k) for k in seg]
            nodes = [liquid_node_global[i] for i in idx_in_order]
            seg_lon.append(float(np.mean([mesh.node_lon[n] for n in nodes])))
            seg_lat.append(float(np.mean([mesh.node_lat[n] for n in nodes])))
        ref_lon = min(seg_lon)
        ref_lat = min(seg_lat)

        const_names = tidal.get("constituents", ["M2", "S2", "K1", "O1"])
        source = tidal.get("source", "synthetic")

        seg_eta: list[np.ndarray] = []
        for s_idx in range(n_segments):
            rep_lon, rep_lat = seg_lon[s_idx], seg_lat[s_idx]
            if source == "synthetic":
                from model.forcing import make_synthetic_tidal_boundary

                bnd = make_synthetic_tidal_boundary(
                    1,
                    amplitude=tidal.get("amplitude", 0.5),
                    constituents=const_names,
                )
            else:
                tidal_path = tidal.get("path")
                if not tidal_path:
                    raise ValueError(
                        "tidal_forcing.path is required for non-synthetic runs"
                    )
                consts = read_tidal_constituents(
                    source, tidal_path, const_names, [rep_lon], [rep_lat]
                )
                bnd = build_tidal_boundary(consts)
            lag = _phase_lag_seconds(rep_lon, rep_lat, ref_lon, ref_lat, config)
            omega = np.asarray(bnd.omega)
            # Retard the phase by omega * lag so the tide travels across the box.
            bnd.phase = bnd.phase - np.outer(omega, np.array([lag], dtype=np.float64))
            eta = bnd.evaluate(times)
            seg_eta.append(eta if eta.ndim == 1 else eta[:, 0])
        liquid_series = np.column_stack(seg_eta)  # (nt, n_segments)
        write_liq(times, liquid_series, liq_path, nliq=n_segments)
        nliq = n_segments
    else:
        write_liq(times, np.zeros((len(times), 0)), liq_path, nliq=0)
        nliq = 0

    return BoundarySet(
        cli_path=cli_path,
        liq_path=liq_path,
        n_boundary_points=nbnd,
        liquid_point_order=liquid_point_order,
        liquid_node_global=liquid_node_global,
        nliq=nliq,
        n_segments=n_segments,
    )
