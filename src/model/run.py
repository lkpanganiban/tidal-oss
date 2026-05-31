"""Main entry point for the tidal hydrodynamic screening model.

Usage:
    python -m model.run [--config path/to/config.yaml] [--output-dir path/]

If no bathymetry file is provided, the model runs with a synthetic
flat-bottom domain suitable for testing and demonstration.
"""

from __future__ import annotations

import logging
import os
from argparse import ArgumentParser

import numpy as np
import yaml

from .bathymetry import load_gebco, regrid_bathymetry, elevation_to_depth
from .forcing import (
    make_synthetic_tidal_boundary,
    build_tidal_boundary,
    read_tidal_constituents,
)
from .grid import StructuredGrid
from .output import (
    create_results_dataset,
    write_netcdf,
    write_mean_power_geotiff,
    write_hotspots_geojson,
)
from .solver import ShallowWaterSolver, G
from .utils import cfl_timestep

logger = logging.getLogger("tidal_model")


def make_test_grid(nx: int = 60, ny: int = 40, dx: float = 2000.0, dy: float = 2000.0) -> StructuredGrid:
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

    grid.lon = np.meshgrid(np.arange(nx) * dx / 111320.0 + 120.0,
                           np.arange(ny) * dy / 111320.0 + 10.0)[0]
    grid.lat = np.meshgrid(np.arange(nx) * dx / 111320.0 + 120.0,
                           np.arange(ny) * dy / 111320.0 + 10.0)[1]

    y_idx = np.arange(ny) * dy
    x_idx = np.arange(nx) * dx
    yy, xx = np.meshgrid(y_idx, x_idx, indexing="ij")

    h = np.full((ny, nx), 100.0)
    mid_y = ny // 2
    for j in range(ny):
        dist = abs(j - mid_y) * dy
        h[j, :] = np.where(dist < 30000.0, 50.0 + dist * 0.005, 200.0)

    grid.h = h
    grid.mask = np.ones((ny, nx), dtype=bool)
    grid.h_u = (np.column_stack([h, h[:, -1:]]) + np.column_stack([h[:, :1], h])) / 2
    grid.h_v = (np.row_stack([h, h[-1:, :]]) + np.row_stack([h[:1, :], h])) / 2
    grid.mask_u[:] = True
    grid.mask_v[:] = True

    grid.open_boundary[:, 0] = True
    grid.open_boundary[:, -1] = True

    return grid


def run(config: dict) -> str:
    """Run the model and return the path to the output GeoTIFF."""
    logger.setLevel(config.get("logging", {}).get("level", "INFO"))
    logging.basicConfig(
        level=logger.level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    domain = config["domain"]
    sim = config["simulation"]
    out_cfg = config["output"]
    tidal = config.get("tidal_forcing", {})

    # ---- 1. Build or load grid ----
    if config.get("bathymetry", {}).get("path"):
        bathy_cfg = config["bathymetry"]
        logger.info("Loading GEBCO from %s", bathy_cfg["path"])
        lon, lat, elev = load_gebco(
            bathy_cfg["path"],
            lon_min=domain["lon_min"],
            lon_max=domain["lon_max"],
            lat_min=domain["lat_min"],
            lat_max=domain["lat_max"],
        )
        lon, lat, elev = regrid_bathymetry(
            lon, lat, elev, resolution_km=domain["resolution_km"]
        )
        depth = elevation_to_depth(elev)
        land_mask = bathy_cfg.get("land_shapefile")
        if land_mask:
            from .bathymetry import build_land_mask
            land_mask = build_land_mask(lon, lat, land_mask)
        else:
            land_mask = elev > 0.0
        depth = np.clip(depth, bathy_cfg.get("min_depth", 2.0), bathy_cfg.get("max_depth", 6000.0))

        grid = StructuredGrid.from_bathymetry(
            lon, lat, depth, land_mask=land_mask, min_depth=bathy_cfg.get("min_depth", 2.0)
        )
    else:
        logger.info("No bathymetry file — using synthetic test grid")
        grid = make_test_grid()

    # ---- 2. Set up open boundaries ----
    tidal_source = tidal.get("source", "synthetic")

    if tidal_source == "synthetic":
        logger.info(
            "Using synthetic M2 tidal boundary (amplitude=%.2f m)",
            tidal.get("amplitude", 0.5),
        )
        tidal_bnd = make_synthetic_tidal_boundary(
            grid.open_boundary.sum(),
            amplitude=tidal.get("amplitude", 0.5),
            constituents=tidal.get("constituents"),
        )
    elif tidal_source in ("fes2014", "fes", "tpxo9", "tpxo", "got", "got4.10c", "got4.10"):
        tidal_path = tidal.get("path")
        if not tidal_path:
            raise ValueError(
                f"tidal_forcing.path is required for source '{tidal_source}'"
            )
        logger.info(
            "Loading %s constituents from %s", tidal_source, tidal_path
        )
        const_names = tidal.get("constituents", ["M2", "S2", "K1", "O1"])
        lon_bnd = grid.lon[grid.open_boundary]
        lat_bnd = grid.lat[grid.open_boundary]
        consts = read_tidal_constituents(
            tidal_source, tidal_path, const_names, lon_bnd, lat_bnd
        )
        tidal_bnd = build_tidal_boundary(consts)
    else:
        raise ValueError(f"Unknown tidal_forcing.source: {tidal_source}")

    # ---- 3. Initialise solver ----
    solver = ShallowWaterSolver(
        grid,
        cd=sim.get("cd", 0.0025),
        ah=sim.get("ah", 0.0),
        advection=sim.get("advection", False),
        rho=sim.get("rho", 1025.0),
    )

    if grid.open_boundary.any():
        solver.set_open_boundary_eta(tidal_bnd)

    # ---- 4. Determine time step ----
    dt = sim.get("dt")
    if dt is None:
        dt = cfl_timestep(
            grid.dx, grid.dy, grid.h_max, safety=sim.get("cfl_safety", 0.8)
        )
        logger.info("Auto-computed dt = %.2f s (CFL safety = %.2f)", dt, sim.get("cfl_safety", 0.8))

    duration = sim["duration_days"] * 86400.0

    # ---- 5. Run ----
    total_vol0 = solver.total_volume()

    save_interval = out_cfg.get("save_interval_hours", 1.0) * 3600.0
    next_save = 0.0
    snapshots: list[dict] = []

    def snapshot_callback(solv, step_n):
        nonlocal next_save
        if solv.time >= next_save:
            spd = solv.compute_power_density()
            snapshots.append({
                "t": solv.time,
                "eta": solv.eta.copy(),
                "u": solv.u.copy(),
                "v": solv.v.copy(),
                "power": spd,
            })
            next_save += save_interval
        return None

    progress_interval = config.get("logging", {}).get("progress_interval_hours", 1.0) * 3600.0
    solver.run(
        dt=dt,
        duration=duration,
        callback=snapshot_callback,
        progress_interval=progress_interval,
    )

    # ---- 6. Mass conservation check ----
    total_vol1 = solver.total_volume()
    logger.info(
        "Mass check: initial volume = %.3e, final = %.3e, drift = %.2e %%",
        total_vol0,
        total_vol1,
        100.0 * abs(total_vol1 - total_vol0) / max(total_vol0, 1.0),
    )

    # ---- 7. Post-process & output ----
    os.makedirs(out_cfg["dir"], exist_ok=True)

    if snapshots:
        nt = len(snapshots)
        times = np.array([s["t"] for s in snapshots])
        eta_hist = np.stack([s["eta"] for s in snapshots])
        u_hist = np.stack([s["u"] for s in snapshots])
        v_hist = np.stack([s["v"] for s in snapshots])
        power_hist = np.stack([s["power"] for s in snapshots])

        power_mean = np.mean(power_hist, axis=0)

        nc_path = os.path.join(out_cfg["dir"], "results.nc")
        ds = create_results_dataset(grid, times, eta_hist, u_hist, v_hist, power_hist)
        write_netcdf(ds, nc_path)
        logger.info("Wrote NetCDF: %s", nc_path)
    else:
        power_mean = solver.compute_power_density()

    tif_path = os.path.join(out_cfg["dir"], out_cfg["final_geotiff"])
    write_mean_power_geotiff(grid, power_mean, tif_path)
    logger.info("Wrote GeoTIFF: %s", tif_path)

    geojson_path = os.path.join(out_cfg["dir"], out_cfg.get("hotspots_geojson", "hotspots.geojson"))
    threshold = out_cfg.get("hotspot_threshold", 200.0)
    write_hotspots_geojson(grid, power_mean, threshold, geojson_path)
    logger.info("Wrote hotspots GeoJSON: %s", geojson_path)

    # ---- 8. Summary stats ----
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
    parser.add_argument("--output-dir", "-o", default=None, help="Override output directory")
    parser.add_argument("--duration-days", type=float, default=None, help="Override simulation duration")
    parser.add_argument("--resolution-km", type=float, default=None, help="Override grid resolution")
    args = parser.parse_args()

    config_path = args.config
    if config_path is None:
        config_path = os.path.join(os.path.dirname(__file__), "config.yaml")

    with open(config_path) as f:
        config = yaml.safe_load(f)

    if args.output_dir:
        config.setdefault("output", {})["dir"] = args.output_dir
    if args.duration_days:
        config.setdefault("simulation", {})["duration_days"] = args.duration_days
    if args.resolution_km:
        config.setdefault("domain", {})["resolution_km"] = args.resolution_km

    out_path = run(config)
    print(f"\nDone. GeoTIFF written to: {out_path}")


if __name__ == "__main__":
    main()
