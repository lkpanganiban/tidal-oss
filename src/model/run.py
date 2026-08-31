"""Main entry point for the tidal hydrodynamic screening model.

Usage:
    python -m model.run [--config path/to/config.yaml] [--output-dir path/]
                        [--duration-days N] [--resolution-km N]
                        [--tidal-source source] [--resume path/to/results.nc]

If no bathymetry file is available, the model runs with a synthetic
flat-bottom domain suitable for testing and demonstration.
"""

from __future__ import annotations

import logging
import os
from argparse import ArgumentParser
from typing import TYPE_CHECKING

import numpy as np

from .bathymetry import (
    build_land_mask,
    elevation_to_depth,
    load_gebco,
    regrid_bathymetry,
)
from .config import TIDAL_SOURCES, load_config, validate_config

if TYPE_CHECKING:
    from .telemac.case import PreparedCase
    from .telemac.hotspots import HotspotRegion
from .forcing import (
    build_tidal_boundary,
    make_synthetic_tidal_boundary,
    read_tidal_constituents,
)
from .grid import StructuredGrid, distance_to_coast_km
from .output import (
    NetCDFStreamWriter,
    max_speed_from_netcdf,
    mean_power_from_netcdf,
    read_last_state,
    write_hotspots_geojson,
    write_mean_power_geotiff,
    write_raster_geotiff,
)
from .solver import ShallowWaterSolver
from .utils import cfl_timestep, coriolis, speed

logger = logging.getLogger("tidal_model")


def configure_logging(level: str = "INFO") -> None:
    """Set up root logging for the CLI (idempotent)."""
    logging.basicConfig(
        level=getattr(logging, str(level).upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )
    logger.setLevel(getattr(logging, str(level).upper(), logging.INFO))


def make_test_grid(
    nx: int = 60, ny: int = 40, dx: float = 2000.0, dy: float = 2000.0
) -> StructuredGrid:
    """Create a simple rectangular domain with a sloping channel for testing."""
    grid = StructuredGrid.from_uniform(
        nx=nx,
        ny=ny,
        dx=dx,
        dy=dy,
        x0=0.0,
        y0=0.0,
        lat0=12.5,
    )

    lon = np.arange(nx) * dx / 111320.0 + 120.0
    lat = np.arange(ny) * dy / 111320.0 + 10.0
    grid.lon, grid.lat = np.meshgrid(lon, lat)

    h = np.full((ny, nx), 100.0)
    mid_y = ny // 2
    for j in range(ny):
        dist = abs(j - mid_y) * dy
        h[j, :] = np.where(dist < 30000.0, 50.0 + dist * 0.005, 200.0)

    grid.h = h
    grid.mask = np.ones((ny, nx), dtype=bool)
    grid.h_u = (np.column_stack([h, h[:, -1:]]) + np.column_stack([h[:, :1], h])) / 2
    grid.h_v = (np.vstack([h, h[-1:, :]]) + np.vstack([h[:1, :], h])) / 2
    grid.mask_u[:] = True
    grid.mask_v[:] = True
    grid.f[:] = np.asarray(coriolis(grid.lat), dtype=np.float64)

    grid.open_boundary[:, 0] = True
    grid.open_boundary[:, -1] = True

    return grid


def _build_grid(config: dict) -> tuple[StructuredGrid, str | None]:
    """Load bathymetry and build the model grid.

    Returns (grid, tidal_source).  Falls back to a synthetic grid with a
    warning when bathymetry.path is unset or the file is missing.
    """
    domain = config["domain"]
    bathy_cfg = config["bathymetry"]
    bathy_path = bathy_cfg.get("path")

    if bathy_path and not os.path.isfile(bathy_path):
        logger.warning(
            "bathymetry.path set (%s) but file not found — falling back to a "
            "synthetic test grid. Download GEBCO and set a valid path for a "
            "production run.",
            bathy_path,
        )
        bathy_path = None

    if bathy_path:
        logger.info("Loading GEBCO from %s", bathy_path)
        lon, lat, elev = load_gebco(
            bathy_path,
            lon_min=domain["lon_min"],
            lon_max=domain["lon_max"],
            lat_min=domain["lat_min"],
            lat_max=domain["lat_max"],
        )
        lon, lat, elev = regrid_bathymetry(
            lon, lat, elev, resolution_km=domain["resolution_km"]
        )
        depth = elevation_to_depth(elev)
        land_shp = bathy_cfg.get("land_shapefile")
        land_mask = build_land_mask(lon, lat, land_shp) if land_shp else elev > 0.0
        depth = np.clip(
            depth,
            bathy_cfg.get("min_depth", 2.0),
            bathy_cfg.get("max_depth", 6000.0),
        )

        grid = StructuredGrid.from_bathymetry(
            lon,
            lat,
            depth,
            land_mask=land_mask,
            min_depth=bathy_cfg.get("min_depth", 2.0),
        )
        return grid, None

    logger.info("No bathymetry file — using synthetic test grid")
    return make_test_grid(), None


def _build_tidal_boundary(grid: StructuredGrid, tidal: dict):
    """Build the open-boundary elevation forcing from the config."""
    tidal_source = tidal.get("source", "synthetic")

    if tidal_source == "synthetic":
        logger.info(
            "Using synthetic M2 tidal boundary (amplitude=%.2f m)",
            tidal.get("amplitude", 0.5),
        )
        return make_synthetic_tidal_boundary(
            grid.open_boundary.sum(),
            amplitude=tidal.get("amplitude", 0.5),
            constituents=tidal.get("constituents"),
        ), tidal_source

    if tidal_source in TIDAL_SOURCES and tidal_source != "synthetic":
        tidal_path = tidal.get("path")
        if not tidal_path:
            raise ValueError(
                f"tidal_forcing.path is required for source '{tidal_source}'"
            )
        const_names = tidal.get("constituents", ["M2", "S2", "K1", "O1"])
        lon_bnd = grid.lon[grid.open_boundary]
        lat_bnd = grid.lat[grid.open_boundary]
        logger.info("Loading %s constituents from %s", tidal_source, tidal_path)
        consts = read_tidal_constituents(
            tidal_source, tidal_path, const_names, lon_bnd, lat_bnd
        )
        return build_tidal_boundary(consts), tidal_source

    raise ValueError(f"Unknown tidal_forcing.source: {tidal_source}")


def build_screening_grid(config: dict):
    """Public wrapper around :func:`_build_grid` returning the structured grid."""
    return _build_grid(config)[0]


def run_model(config: dict, resume_from: str | None = None) -> str:
    """Dispatch to the selected engine (``python`` or ``telemac2d``)."""
    engine = config.get("engine", {}).get("name", "python")
    if engine == "telemac2d":
        return run_telemac_pipeline(config, resume_from)
    if engine not in ("python", "telemac2d"):
        raise ValueError(f"engine.name '{engine}' not supported (python | telemac2d)")
    return run(config, resume_from)


def run_telemac_pipeline(
    config: dict, resume_from: str | None = None, *, dry_run: bool = False
) -> str:
    """Screen (if needed), cluster hotspots, refine with TELEMAC-2D, post-process.

    The screening model is used to locate energetic regions; each region becomes
    a self-contained TELEMAC case run inside the public Docker image.  Canonical
    outputs for every region are written to ``<output>/telemac/<region_id>/`` so
    the existing Flask/MapLibre stack can visualise any refinement independently
    of the archipelago-wide screening view.
    """
    from .telemac.postprocess import postprocess_case
    from .telemac.runner import run_case

    configure_logging(config.get("logging", {}).get("level", "INFO"))

    out_cfg = config["output"]
    out_dir = out_cfg["dir"]
    os.makedirs(out_dir, exist_ok=True)

    hotspots_path = os.path.join(
        out_dir, out_cfg.get("hotspots_geojson", "hotspots.geojson")
    )
    if not os.path.isfile(hotspots_path):
        logger.info(
            "No screening hotspots found at %s — running Python screening first",
            hotspots_path,
        )
        run(config, resume_from)

    grid = build_screening_grid(config)
    cases_dir = config.get("telemac2d", {}).get("cases_dir", "cases")
    prepared = prepare_regions(config, grid, hotspots_path, cases_dir)

    telemac_cfg = config.get("telemac2d", {})
    docker = bool(telemac_cfg.get("docker", True))
    last_out = None
    for region, pc in prepared:
        run_case(pc.case_dir, docker=docker, dry_run=dry_run)
        region_out = os.path.join(out_dir, "telemac", region.id)
        summary = postprocess_case(pc.case_dir, config, region_out, region_id=region.id)
        recon = summary.get("reconciliation", {})
        if recon.get("screening_max_power"):
            logger.info(
                "  %s [%s]: TELEMAC max power %.0f W/m² vs screening %.0f W/m² "
                "(%.2fx) — reconciliation.json written",
                region.id,
                getattr(region, "axis", "?"),
                recon.get("telemac_max_power", 0.0),
                recon["screening_max_power"],
                recon.get("ratio_telemac_to_screening", float("nan")),
            )
        last_out = region_out

    if telemac_cfg.get("postprocess", {}).get("write_to_output_root") and prepared:
        assert last_out is not None  # a non-empty prepared list implies a run
        _copy_region_to_output_root(last_out, out_dir, out_cfg)

    logger.info(
        "TELEMAC refinement complete. Region outputs under %s",
        os.path.join(out_dir, "telemac"),
    )
    return last_out or out_dir


def prepare_regions(
    config: dict,
    grid,
    hotspots_path: str,
    cases_dir: str,
) -> list[tuple[HotspotRegion, PreparedCase]]:
    """Cluster *hotspots_path* into refinement regions and write each case dir.

    Shared by the CLI and the in-process pipeline so both paths agree on how
    regions are selected (explicit ``telemac2d.mesh.boundary.sites`` take
    precedence over inferred hotspot clustering) and how each case is assembled.
    Returns ``(region, PreparedCase)`` pairs.  *hotspots_path* must already
    exist (callers decide whether to synthesise it first).
    """
    from .telemac.case import prepare_case
    from .telemac.hotspots import (
        cluster_hotspots,
        regions_from_sites,
        save_regions,
    )

    telemac_cfg = config.get("telemac2d", {})
    mesh_cfg = telemac_cfg.get("mesh", {})
    boundary_cfg = mesh_cfg.get("boundary", {})

    # Explicit strait-site definitions (config) take precedence over inferred
    # hotspot clustering — they let the analyst align each refined domain with
    # the actual channel and guarantee both liquid boundaries reach open water.
    sites = boundary_cfg.get("sites")
    if sites:
        regions = regions_from_sites(sites)
        logger.info("Using %d explicit strait site(s) from config", len(regions))
    else:
        regions = cluster_hotspots(
            hotspots_path,
            cluster_radius_km=float(boundary_cfg.get("cluster_radius_km", 15.0)),
            margin_km=float(boundary_cfg.get("margin_km", 10.0)),
            max_regions=int(boundary_cfg.get("max_regions", 3)),
            channel_buffer_km=boundary_cfg.get("channel_buffer_km"),
        )
    os.makedirs(cases_dir, exist_ok=True)
    save_regions(regions, os.path.join(cases_dir, "regions.json"))
    logger.info("Prepared %d refinement region(s)", len(regions))

    tidal = config.get("tidal_forcing", {})
    prepared = []
    for region in regions:
        supplied = (
            mesh_cfg.get("supplied_mesh")
            if mesh_cfg.get("source") == "supplied"
            else None
        )
        try:
            pc = prepare_case(
                region, config, tidal, cases_dir, grid=grid, supplied_mesh=supplied
            )
        except ValueError as exc:
            # An unrefinable region (e.g. no wet path between open edges)
            # should not abort the remaining refinements.
            logger.warning("Skipping %s: %s", region.id, exc)
            continue
        prepared.append((region, pc))
    return prepared


def _copy_region_to_output_root(region_out: str, out_dir: str, out_cfg: dict) -> None:
    import shutil

    for key in (
        "results_nc",
        "final_geotiff",
        "max_speed_geotiff",
        "bathymetry_geotiff",
        "distance_geotiff",
        "hotspots_geojson",
    ):
        src = os.path.join(region_out, os.path.basename(out_cfg.get(key, "")))
        if os.path.isfile(src):
            shutil.copyfile(src, os.path.join(out_dir, os.path.basename(src)))


def run(config: dict, resume_from: str | None = None) -> str:
    """Run the model and return the path to the output GeoTIFF.

    Parameters
    ----------
    config : dict
        Validated configuration (see :func:`model.config.validate_config`).
    resume_from : str or None
        Path to a previous ``results.nc``.  When given, the run continues
        from the last recorded snapshot instead of starting from rest.
    """
    configure_logging(config.get("logging", {}).get("level", "INFO"))
    validate_config(config)

    domain = config["domain"]
    sim = config["simulation"]
    out_cfg = config["output"]
    tidal = config.get("tidal_forcing", {})

    # ---- 1. Build or load grid ----
    grid, _ = _build_grid(config)

    # ---- 2. Set up open boundaries ----
    tidal_bnd, tidal_source = _build_tidal_boundary(grid, tidal)

    # ---- 3. Initialise solver ----
    solver = ShallowWaterSolver(
        grid,
        cd=sim.get("cd", 0.0025),
        ah=sim.get("ah", 0.0),
        advection=sim.get("advection", False),
        rho=sim.get("rho", 1025.0),
        use_numba=sim.get("use_numba"),
    )

    if grid.open_boundary.any():
        solver.set_open_boundary_eta(tidal_bnd)

    # ---- 4. Determine time step and duration ----
    dt = sim.get("dt")
    if dt is None:
        dt = cfl_timestep(
            grid.dx, grid.dy, grid.h_max, safety=sim.get("cfl_safety", 0.5)
        )
        logger.info(
            "Auto-computed dt = %.2f s (CFL safety = %.2f)",
            dt,
            sim.get("cfl_safety", 0.5),
        )

    duration = sim["duration_days"] * 86400.0

    # ---- 5. Resume support ----
    start_time = 0.0
    if resume_from:
        if not os.path.isfile(resume_from):
            raise FileNotFoundError(f"Resume file not found: {resume_from}")
        t_last, eta0, u0, v0 = read_last_state(resume_from)
        start_time = t_last
        solver.set_initial_conditions(eta0=eta0, u0=u0, v0=v0)
        solver._t = t_last  # noqa: SLF001 — solver tracks its own clock
        logger.info(
            "Resuming from %s at t=%.2f d (%.1f d remaining)",
            resume_from,
            t_last / 86400.0,
            (duration - t_last) / 86400.0,
        )
        if t_last >= duration:
            logger.warning(
                "Resume state is already past the target duration — post-processing only."
            )

    run_duration = max(duration - start_time, 0.0)

    total_vol0 = solver.total_volume()

    # ---- 6. Run (streaming snapshots to NetCDF) ----
    nc_path = os.path.join(out_cfg["dir"], out_cfg.get("results_nc", "results.nc"))
    os.makedirs(out_cfg["dir"], exist_ok=True)

    save_interval = out_cfg.get("save_interval_hours", 1.0) * 3600.0
    next_save = np.ceil(start_time / save_interval) * save_interval

    power_sum = np.zeros(grid.shape, dtype=np.float64)
    speed_max = np.zeros(grid.shape, dtype=np.float64)
    power_count = 0

    writer_mode = "a" if resume_from else "w"
    with NetCDFStreamWriter(
        nc_path,
        grid,
        rho=solver.rho,
        cd=solver.cd,
        extra_attrs={
            "source": tidal_source,
            "constituents": ",".join(tidal.get("constituents", ["M2"])),
            "duration_days": sim.get("duration_days"),
            "resolution_km": domain.get("resolution_km"),
            "domain": (
                f"{domain.get('lon_min')},{domain.get('lon_max')},"
                f"{domain.get('lat_min')},{domain.get('lat_max')}"
            ),
        },
        mode=writer_mode,
    ) as writer:

        def snapshot_callback(solv, step_n):
            nonlocal next_save, power_sum, speed_max, power_count
            if solv.time >= next_save:
                spd = solv.compute_power_density()
                sp = speed(solv.u, solv.v)
                writer.write_snapshot(
                    solv.time,
                    solv.eta.copy(),
                    solv.u.copy(),
                    solv.v.copy(),
                    spd,
                )
                power_sum += spd
                np.maximum(speed_max, sp, out=speed_max)
                power_count += 1
                next_save += save_interval
            return None

        progress_interval = (
            config.get("logging", {}).get("progress_interval_hours", 1.0) * 3600.0
        )
        if run_duration > 0:
            solver.run(
                dt=dt,
                duration=run_duration,
                callback=snapshot_callback,
                progress_interval=progress_interval,
            )

    # ---- 7. Mass conservation check ----
    total_vol1 = solver.total_volume()
    logger.info(
        "Mass check: initial volume = %.3e, final = %.3e, drift = %.2e %%",
        total_vol0,
        total_vol1,
        100.0 * abs(total_vol1 - total_vol0) / max(total_vol0, 1.0),
    )

    # ---- 8. Post-process & output ----
    if resume_from and os.path.isfile(nc_path):
        # Resumed run: recompute the mean / max over the FULL time series
        # (fresh segment + resumed segment).
        power_mean = mean_power_from_netcdf(nc_path)
        speed_max = max_speed_from_netcdf(nc_path)
        logger.info("Recomputed time-mean power from %s", nc_path)
    elif power_count > 0:
        power_mean = power_sum / power_count
        logger.info("Wrote NetCDF: %s (%d snapshots)", nc_path, power_count)
    else:
        power_mean = solver.compute_power_density()
        speed_max = speed(solver.u, solver.v)

    # Power density (land masked as NaN so the web layer renders it as
    # transparent over the base map)
    tif_path = os.path.join(out_cfg["dir"], out_cfg["final_geotiff"])
    power_layer = np.where(grid.mask, power_mean, np.nan)
    write_mean_power_geotiff(grid, power_layer, tif_path)
    logger.info("Wrote GeoTIFF: %s", tif_path)

    # Max current speed (m/s) — key for turbine cut-in/rated speed screening
    speed_path = os.path.join(
        out_cfg["dir"], out_cfg.get("max_speed_geotiff", "max_current_speed.tif")
    )
    speed_layer = np.where(grid.mask, speed_max, np.nan)
    write_raster_geotiff(
        grid, speed_layer, speed_path, "maximum depth-averaged current speed (m/s)"
    )
    logger.info("Wrote GeoTIFF: %s", speed_path)

    # Bathymetry (m, positive down; land = NaN)
    bathy_path = os.path.join(
        out_cfg["dir"], out_cfg.get("bathymetry_geotiff", "bathymetry.tif")
    )
    depth_layer = np.where(grid.mask, grid.h, np.nan)
    write_raster_geotiff(
        grid, depth_layer, bathy_path, "bathymetric depth (m, positive down)"
    )
    logger.info("Wrote GeoTIFF: %s", bathy_path)

    # Distance to nearest coast (km) — MSP: cabling, navigation, exclusion zones
    dist_path = os.path.join(
        out_cfg["dir"], out_cfg.get("distance_geotiff", "distance_to_coast.tif")
    )
    dist_km = distance_to_coast_km(grid.mask, grid.dx, grid.dy)
    write_raster_geotiff(grid, dist_km, dist_path, "distance to nearest coast (km)")
    logger.info("Wrote GeoTIFF: %s", dist_path)

    geojson_path = os.path.join(
        out_cfg["dir"], out_cfg.get("hotspots_geojson", "hotspots.geojson")
    )
    threshold = out_cfg.get("hotspot_threshold", 200.0)
    write_hotspots_geojson(grid, power_mean, threshold, geojson_path)
    logger.info("Wrote hotspots GeoJSON: %s", geojson_path)

    # ---- 9. Summary stats ----
    active = grid.mask
    p_flat = power_mean[active]
    logger.info("Power density stats [W/m²]:")
    logger.info("  mean  = %.1f", float(np.mean(p_flat)))
    logger.info("  max   = %.1f", float(np.max(p_flat)))
    logger.info("  P95   = %.1f", float(np.percentile(p_flat, 95)))
    n_hotspots = int(np.sum(p_flat >= threshold))
    logger.info("  hotspots (> %.0f W/m²) = %d cells", threshold, n_hotspots)

    return tif_path


def main():
    parser = ArgumentParser(description="Tidal hydrodynamic screening model")
    parser.add_argument("--config", "-c", default=None, help="Path to config YAML")
    parser.add_argument(
        "--output-dir", "-o", default=None, help="Override output directory"
    )
    parser.add_argument(
        "--duration-days", type=float, default=None, help="Override simulation duration"
    )
    parser.add_argument(
        "--resolution-km", type=float, default=None, help="Override grid resolution"
    )
    parser.add_argument(
        "--tidal-source",
        default=None,
        help="Override tidal forcing source: synthetic | got | fes2014 | tpxo9",
    )
    parser.add_argument(
        "--resume",
        default=None,
        metavar="RESULTS_NC",
        help="Continue from the last snapshot in an existing results.nc",
    )
    parser.add_argument(
        "--engine",
        default=None,
        help="Override engine: python (default) | telemac2d",
    )
    args = parser.parse_args()

    config = load_config(args.config)

    # Containerised runs: OUTPUT_DIR env (set by the Dockerfile / compose)
    # overrides the relative output dir in config.yaml.
    if os.environ.get("OUTPUT_DIR"):
        config.setdefault("output", {})["dir"] = os.environ["OUTPUT_DIR"]

    if args.output_dir:
        config.setdefault("output", {})["dir"] = args.output_dir
    if args.duration_days:
        config.setdefault("simulation", {})["duration_days"] = args.duration_days
    if args.resolution_km:
        config.setdefault("domain", {})["resolution_km"] = args.resolution_km
    if args.tidal_source:
        config.setdefault("tidal_forcing", {})["source"] = args.tidal_source
    if args.engine:
        config.setdefault("engine", {})["name"] = args.engine

    out_path = run_model(config, resume_from=args.resume)
    print(f"\nDone. Output written to: {out_path}")


if __name__ == "__main__":
    main()
