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
VELOCITY_PRESCRIBED = 5  # LIUBOR/LIVBOR = 5: velocity imposed from the .liq file

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


def write_cli(
    mesh: RefinementMesh,
    is_liquid: list[bool],
    path: str,
    segments: list[list[int]] | None = None,
    velocity_prescribed: bool = False,
) -> None:
    """Write the TELEMAC ``.cli`` boundary-conditions file.

    TELEMAC v7/v8 expects 13 whitespace-separated columns per boundary point
    (in IPOBO order)::

        LIEBOR LIUBOR LIVBOR 0.0 0.0 0.0 0.0 NUMLIQ 0.0 0.0 0.0 NODE IPOBO

    where ``NODE`` is the global (1-based) mesh-node index of the point and
    ``IPOBO`` is the 1-based boundary-point counter.  ``LIEBOR=5`` marks a
    liquid (prescribed-elevation) point and the 8th column (``NUMLIQ``) is the
    1-based index of the liquid boundary segment that point belongs to -- it
    must match a column of the ``.liq`` file.  ``LIEBOR=2`` marks a solid wall.

    With ``velocity_prescribed`` (Thompson nesting) liquid points also carry
    ``LIUBOR=LIVBOR=5`` so TELEMAC reads ``U(i)``/``V(i)`` velocity columns.
    """
    geom = mesh.geometry
    ipobo = geom.ipobo
    nbnd = int((ipobo > 0).sum())

    # IPOBO (1-based) -> liquid-boundary segment index (1-based).
    seg_of_k: dict[int, int] = {}
    if segments:
        for idx, seg in enumerate(segments, start=1):
            for k in seg:
                seg_of_k[k] = idx

    lines = []
    for k in range(1, nbnd + 1):
        node = int(np.where(ipobo == k)[0][0]) + 1  # 1-based global node
        if is_liquid[k - 1]:
            liebor = LIQUID_ELEVATION
            if velocity_prescribed:
                liubor = livbor = VELOCITY_PRESCRIBED
            else:
                liubor = livbor = FREE
            # Column 8 is the liquid-boundary number, NOT a "type".
            litbor = seg_of_k.get(k, 1)
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
    times: np.ndarray,
    liquid_series: np.ndarray,
    path: str,
    nliq: int | None = None,
    uv_series: tuple[np.ndarray, np.ndarray] | None = None,
) -> None:
    """Write the TELEMAC ``.liq`` liquid-boundary time series.

    TELEMAC v7/v8 reads this file with ``READ_FIC_FRLIQ``, matching columns
    by name.  With ``uv_series`` (Thompson nesting) the file additionally
    carries ``U(i)``/``V(i)`` east/north velocity columns per boundary, and
    the reader returns them to the characteristic boundary treatment.

    ``liquid_series`` has shape ``(nt, nliq)``; ``uv_series`` is a pair of
    ``(nt, nliq)`` arrays.
    """
    times = np.asarray(times, dtype=np.float64)
    liquid_series = np.asarray(liquid_series, dtype=np.float64)
    if liquid_series.ndim == 3:
        # Backwards-compatible: collapse the (nt, nliq, n_liquid) form.
        liquid_series = liquid_series[:, 0, :]
    nt, ncols = liquid_series.shape
    if nliq is None:
        nliq = ncols
    if uv_series is not None:
        u_s = np.atleast_2d(np.asarray(uv_series[0], dtype=np.float64))
        v_s = np.atleast_2d(np.asarray(uv_series[1], dtype=np.float64))
        if u_s.shape[1] == 1 and nliq > 1:
            u_s = np.repeat(u_s, nliq, axis=1)
            v_s = np.repeat(v_s, nliq, axis=1)

    header = ["T"] + [f"SL({i})" for i in range(1, nliq + 1)]
    units = ["s"] + ["m"] * nliq
    if uv_series is not None:
        header += [f"U({i})" for i in range(1, nliq + 1)]
        header += [f"V({i})" for i in range(1, nliq + 1)]
        units += ["m/s"] * (2 * nliq)
    with open(path, "w") as f:
        # FRLIQ layout expected by TELEMAC v8p1r1 (read_fic_frliq.f): the
        # first line is the variable list and MUST begin with ``T`` (the time
        # keyword); the second line is skipped by the reader (units are
        # conventional); data records follow.  Dropping the units line makes
        # the reader swallow the first data record, so early simulation
        # times read as "out of range".
        f.write(" ".join(header) + "\n")
        f.write(" ".join(units) + "\n")
        for t_idx in range(nt):
            parts = [f"{times[t_idx]:.3f}"]
            parts.extend(f"{val:.6e}" for val in liquid_series[t_idx, :nliq])
            if uv_series is not None:
                parts.extend(f"{val:.6e}" for val in u_s[t_idx, :nliq])
                parts.extend(f"{val:.6e}" for val in v_s[t_idx, :nliq])
            f.write(" ".join(parts) + "\n")


def _phase_lag_seconds(
    rep_lon: float,
    rep_lat: float,
    ref_lon: float,
    ref_lat: float,
    config: dict,
    axis: str | None = None,
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
    axis = axis or boundary_cfg.get("propagation_axis", "lon")
    if axis == "lon":
        metres_per_deg = 111320.0 * math.cos(math.radians(rep_lat))
        dist = (rep_lon - ref_lon) * metres_per_deg
    else:
        metres_per_deg = 110540.0
        dist = (rep_lat - ref_lat) * metres_per_deg
    return float(dist) / float(phase_speed)


def _harmonic_series(
    lons: np.ndarray,
    lats: np.ndarray,
    tidal: dict,
    const_names: list[str],
    source: str,
    ref_lon: float,
    ref_lat: float,
    config: dict,
    propagation_axis: str | None,
    liq_times: np.ndarray,
) -> np.ndarray:
    """Harmonic (GOT/synthetic) elevation series at the given points.

    This is the fallback forcing used when no parent screening solution is
    available; the artificial propagation ramp applies only here.
    """
    from model.forcing import build_tidal_boundary, read_tidal_constituents

    cols: list[np.ndarray] = []
    for rep_lon, rep_lat in zip(lons, lats, strict=True):
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
                source, tidal_path, const_names, [float(rep_lon)], [float(rep_lat)]
            )
            bnd = build_tidal_boundary(consts)
        lag = _phase_lag_seconds(
            float(rep_lon),
            float(rep_lat),
            ref_lon,
            ref_lat,
            config,
            axis=propagation_axis,
        )
        omega = np.asarray(bnd.omega)
        # Retard the phase by omega * lag so the tide travels across the box.
        bnd.phase = bnd.phase - np.outer(omega, np.array([lag], dtype=np.float64))
        eta = bnd.evaluate(liq_times)
        cols.append(eta if eta.ndim == 1 else eta[:, 0])
    return np.column_stack(cols)


def generate_boundaries(
    mesh: RefinementMesh,
    config: dict,
    tidal: dict,
    times: np.ndarray,
    cas_dir: str,
    *,
    edge_types: dict[str, str] | None = None,
    liquid_nodes_file: str | None = None,
    propagation_axis: str | None = None,
    parent_nc: str | None = None,
    parent_grid=None,
    thompson: bool = False,
) -> BoundarySet:
    """Create ``.cli`` and ``.liq`` for a refinement mesh.

    Every liquid boundary point becomes its own liquid boundary: TELEMAC
    prescribes a *uniform* elevation per boundary, and grouping opposite sides
    of the box into one segment (which contiguous IPOBO grouping does when the
    boundary ordering interleaves the edges) would force them *identically*
    and forbid any east--west gradient.

    Forcing source, in order of preference:

    1. **Parent nesting** — when ``parent_nc`` (the screening ``results.nc``)
       and ``parent_grid`` are given, each liquid point receives the parent
       screening model's own elevation, sampled wet-cell-aware at the point.
       This is a true one-way nested child: same constituents, epoch, datum,
       and the parent's spatial amplitude/phase variation.
    2. **Harmonic fallback** — GOT constituents evaluated per point, plus the
       propagation ramp from :func:`_phase_lag_seconds` (used only when no
       parent solution exists).
    """
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

    liquid_point_order = [k for k in range(1, nbnd + 1) if is_liquid[k - 1]]
    liquid_node_global = [int(np.where(ipobo == k)[0][0]) for k in liquid_point_order]

    segments = [[k] for k in liquid_point_order]
    n_segments = len(segments)

    # The .liq file is written at ~hourly cadence (TELEMAC interpolates the
    # liquid-boundary records in time).  Prescribing every solver step on a
    # fine mesh would produce a needlessly huge file with no extra signal —
    # the tidal constituents are smooth at hourly sampling, matching the
    # screening model's forcing cadence.
    dt = float(times[1] - times[0]) if len(times) > 1 else 1.0
    liq_stride = max(1, int(round(3600.0 / max(dt, 1e-6))))
    liq_times = times[::liq_stride]

    # Thompson nesting (parent u,v + eta with characteristic treatment).
    # NOTE: v8p1r1 routes LIUBOR=5 boundaries through DEBIMP flowrate
    # rescaling (PRESCRIBED FLOWRATES required); enable only with a
    # defensible flowrate series.  Elevation-only nesting is the default.
    thompson = thompson and parent_nc is not None and parent_grid is not None

    cli_path = f"{cas_dir}/mesh.cli"
    liq_path = f"{cas_dir}/mesh.liq"
    write_cli(
        mesh, is_liquid, cli_path, segments=segments, velocity_prescribed=thompson
    )

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
        uv_series = None  # Thompson velocity series; present only under parent nesting

        # --- preferred: one-way nesting in the parent screening solution ---
        if parent_nc and parent_grid is not None:
            from .parent import (
                read_parent_time_coverage,
                sample_parent_elevation,
                sample_parent_velocity,
            )

            p_lon = np.array(
                [mesh.node_lon[n] for n in liquid_node_global], dtype=np.float64
            )
            p_lat = np.array(
                [mesh.node_lat[n] for n in liquid_node_global], dtype=np.float64
            )
            p_times, p_series, resolved = sample_parent_elevation(
                parent_nc, parent_grid, p_lon, p_lat
            )
            if thompson:
                _, p_u, p_v = sample_parent_velocity(
                    parent_nc, parent_grid, p_lon, p_lat
                )
                uv_series = (p_u, p_v)
            # TELEMAC must never ask for a time past the parent's last record.
            t_first, t_last = read_parent_time_coverage(parent_nc)
            if float(times[-1]) > t_last + 1.0:
                raise ValueError(
                    f"refinement duration ({times[-1] / 86400:.1f} d) exceeds the "
                    f"parent solution ({t_last / 86400:.1f} d); align "
                    "simulation.duration_days with the screening run"
                )
            if not resolved.all():
                # Harmonic fallback for the (rare) points without a wet parent
                # cell nearby; parent series everywhere else.
                fb_idx = [i for i, ok in enumerate(resolved) if not ok]
                fb = _harmonic_series(
                    p_lon[fb_idx],
                    p_lat[fb_idx],
                    tidal,
                    const_names,
                    source,
                    ref_lon,
                    ref_lat,
                    config,
                    propagation_axis,
                    liq_times,
                )
                for col, i in enumerate(fb_idx):
                    p_series[:, i] = fb[:, col]
                if thompson:
                    # No parent flow state for these points — leave their
                    # velocity columns at rest.
                    for i in fb_idx:
                        uv_series[0][:, i] = 0.0
                        uv_series[1][:, i] = 0.0
            if p_times[0] > 0.0:
                # The parent's first snapshot is a few seconds in; prepend a
                # t=0 record so TELEMAC's first boundary query is in range.
                p_times = np.concatenate([[0.0], p_times])
                p_series = np.vstack([p_series[:1], p_series])
                if uv_series is not None:
                    uv_series = (
                        np.vstack([uv_series[0][:1], uv_series[0]]),
                        np.vstack([uv_series[1][:1], uv_series[1]]),
                    )
            liquid_series = p_series
            liq_file_times = p_times
        else:
            liquid_series = _harmonic_series(
                np.array(seg_lon),
                np.array(seg_lat),
                tidal,
                const_names,
                source,
                ref_lon,
                ref_lat,
                config,
                propagation_axis,
                liq_times,
            )
            liq_file_times = liq_times

        write_liq(
            liq_file_times,
            liquid_series,
            liq_path,
            nliq=n_segments,
            uv_series=uv_series,
        )
        nliq = n_segments
    else:
        write_liq(liq_times, np.zeros((len(liq_times), 0)), liq_path, nliq=0)
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
