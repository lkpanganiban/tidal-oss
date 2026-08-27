"""Convert TELEMAC Selafin results into the canonical screening outputs.

The web application and downstream analyses expect a fixed output contract
(``results.nc`` + a set of GeoTIFFs + a hotspot GeoJSON) produced by the
screening model.  This module reads the unstructured TELEMAC result file
(``r2d.slf``), rasterises the node fields onto a regular longitude/latitude
grid covering the refinement region, and writes exactly the same products so
the Flask/MapLibre stack is engine-agnostic.

Rasterisation uses scipy where available and falls back to inverse-distance
weighting, so the routine never hard-fails on minimal environments.
"""

from __future__ import annotations

import json
import os

import numpy as np

from .mesh import RefinementMesh, unproject_from_local_meters
from .selafin import read_serafin


def _target_grid(mesh: RefinementMesh, resolution_m: float):
    from model.grid import StructuredGrid

    bbox = mesh.bbox
    lat0 = (
        mesh.lat0
        if mesh.coordinates_are_meters
        else float(np.mean([bbox["lat_min"], bbox["lat_max"]]))
    )
    dlon = resolution_m / (111320.0 * np.cos(np.radians(lat0)))
    dlat = resolution_m / 110540.0
    nx = max(2, int(round((bbox["lon_max"] - bbox["lon_min"]) / dlon)) + 1)
    ny = max(2, int(round((bbox["lat_max"] - bbox["lat_min"]) / dlat)) + 1)
    lon1d = np.linspace(bbox["lon_min"], bbox["lon_max"], nx)
    lat1d = np.linspace(bbox["lat_min"], bbox["lat_max"], ny)
    lon2d, lat2d = np.meshgrid(lon1d, lat1d)

    grid = StructuredGrid.from_uniform(
        nx=nx, ny=ny, dx=resolution_m, dy=resolution_m, lat0=lat0
    )
    grid.lon = lon2d
    grid.lat = lat2d
    return grid


def postprocess_case(
    case_dir: str,
    config: dict,
    out_dir: str,
    *,
    region_id: str | None = None,
) -> dict:
    """Read ``r2d.slf`` and write canonical outputs into ``out_dir``.

    Returns a dict summarising the products written.
    """
    from model.grid import distance_to_coast_km
    from model.output import (
        NetCDFStreamWriter,
        write_hotspots_geojson,
        write_mean_power_geotiff,
        write_raster_geotiff,
    )

    from .mesh import rasterize_to_grid

    with open(os.path.join(case_dir, "manifest.json")) as f:
        manifest = json.load(f)
    with open(os.path.join(case_dir, "mesh_manifest.json")) as f:
        mesh_meta = json.load(f)

    result_path = os.path.join(case_dir, "r2d.slf")
    if not os.path.isfile(result_path):
        raise FileNotFoundError(f"TELEMAC result file not found: {result_path}")

    telemac_cfg = config.get("telemac2d", {})
    pp_cfg = telemac_cfg.get("postprocess", {})
    resolution_m = float(pp_cfg.get("output_grid_resolution_km", 0.5) * 1000.0)
    rho = float(config.get("simulation", {}).get("rho", 1025.0))
    cd = float(config.get("simulation", {}).get("cd", 0.0025))
    threshold = float(config.get("output", {}).get("hotspot_threshold", 200.0))

    res = read_serafin(result_path)
    node_x = res["node_x"]
    node_y = res["node_y"]
    variables = res["variables"]
    times = res["times"]

    if mesh_meta.get("coordinates_are_meters"):
        node_lon, node_lat = unproject_from_local_meters(
            node_x, node_y, mesh_meta["lon0"], mesh_meta["lat0"]
        )
        triangles = res.get("ikle")
    else:
        node_lon, node_lat = node_x, node_y
        triangles = res.get("ikle")

    grid = _target_grid(
        mesh_meta_to_refinement(mesh_meta, node_lon, node_lat), resolution_m
    )

    eta_name = _first_present(variables, ["ELEVATION Z", "ELEVATION", "FREE SURFACE"])
    u_name = _first_present(variables, ["VELOCITY U", "VELOCITY UX"])
    v_name = _first_present(variables, ["VELOCITY V", "VELOCITY VY"])

    nt = times.shape[0]
    ny, nx = grid.lat.shape
    power_mean = np.zeros((ny, nx), dtype=np.float64)
    speed_max = np.zeros((ny, nx), dtype=np.float64)

    os.makedirs(out_dir, exist_ok=True)
    nc_path = os.path.join(out_dir, manifest.get("results_nc", "results.nc"))
    extra_attrs = {
        "source": "telemac2d",
        "engine": "telemac2d",
        "region": region_id or manifest.get("region_id", ""),
        "image": manifest.get("image", ""),
        "duration_days": manifest.get("duration_days"),
        "resolution_m": resolution_m,
        "domain": f"{grid.lon.min()},{grid.lon.max()},{grid.lat.min()},{grid.lat.max()}",
    }

    with NetCDFStreamWriter(
        nc_path, grid, rho=rho, cd=cd, extra_attrs=extra_attrs, mode="w"
    ) as writer:
        for t_idx in range(nt):
            eta = rasterize_to_grid(
                variables[eta_name][t_idx], node_lon, node_lat, grid.lon, grid.lat, triangles
            )
            if u_name:
                u = rasterize_to_grid(
                    variables[u_name][t_idx], node_lon, node_lat, grid.lon, grid.lat, triangles
                )
            else:
                u = np.zeros_like(eta)
            if v_name:
                v = rasterize_to_grid(
                    variables[v_name][t_idx], node_lon, node_lat, grid.lon, grid.lat, triangles
                )
            else:
                v = np.zeros_like(eta)
            speed = np.sqrt(u**2 + v**2)
            power = 0.5 * rho * speed**3

            power_mean += np.nan_to_num(power)
            speed_max = np.maximum(speed_max, speed)

            u_pad = _pad_u(u)
            v_pad = _pad_v(v)
            writer.write_snapshot(times[t_idx], eta, u_pad, v_pad, power)

    power_mean = np.where(np.isfinite(power_mean), power_mean / max(nt, 1), np.nan)
    # `speed_max` already carries the triangle/land mask (NaN outside the mesh),
    # unlike `power_mean` which was NaN->0 accumulated above. Use it so the
    # power-density raster is not filled across the whole bounding box.
    grid.mask = np.isfinite(speed_max)
    grid.h = np.where(
        grid.mask, _raster_depth(mesh_meta, node_lon, node_lat, grid, triangles), np.nan
    )

    power_tif = os.path.join(
        out_dir, manifest.get("final_geotiff", "tidal_power_density.tif")
    )
    write_mean_power_geotiff(grid, np.where(grid.mask, power_mean, np.nan), power_tif)

    speed_tif = os.path.join(
        out_dir, manifest.get("max_speed_geotiff", "max_current_speed.tif")
    )
    write_raster_geotiff(
        grid,
        np.where(grid.mask, speed_max, np.nan),
        speed_tif,
        "maximum depth-averaged current speed (m/s)",
    )

    bathy_tif = os.path.join(
        out_dir, manifest.get("bathymetry_geotiff", "bathymetry.tif")
    )
    write_raster_geotiff(
        grid, grid.h, bathy_tif, "bathymetric depth (m, positive down)"
    )

    dist_tif = os.path.join(
        out_dir, manifest.get("distance_geotiff", "distance_to_coast.tif")
    )
    dist_km = distance_to_coast_km(grid.mask, grid.dx, grid.dy)
    write_raster_geotiff(grid, dist_km, dist_tif, "distance to nearest coast (km)")

    geojson_path = os.path.join(
        out_dir, manifest.get("hotspots_geojson", "hotspots.geojson")
    )
    write_hotspots_geojson(grid, power_mean, threshold, geojson_path)

    return {
        "results_nc": nc_path,
        "tidal_power_density_tif": power_tif,
        "max_current_speed_tif": speed_tif,
        "bathymetry_tif": bathy_tif,
        "distance_to_coast_tif": dist_tif,
        "hotspots_geojson": geojson_path,
        "n_timesteps": nt,
        "max_power_Wm2": float(np.nanmax(power_mean)) if grid.mask.any() else 0.0,
    }


def mesh_meta_to_refinement(mesh_meta: dict, node_lon, node_lat) -> RefinementMesh:
    from .mesh import RefinementMesh

    return RefinementMesh(
        path=mesh_meta["path"],
        geometry=None,  # type: ignore[arg-type]
        lon0=mesh_meta["lon0"],
        lat0=mesh_meta["lat0"],
        node_lon=np.asarray(node_lon),
        node_lat=np.asarray(node_lat),
        coordinates_are_meters=mesh_meta["coordinates_are_meters"],
        bbox=mesh_meta["bbox"],
    )


def _raster_depth(mesh_meta: dict, node_lon, node_lat, grid, triangles=None) -> np.ndarray:
    from .mesh import rasterize_to_grid

    if mesh_meta.get("node_depth") is not None:
        depth = np.asarray(mesh_meta["node_depth"], dtype=np.float64)
    else:
        depth = np.zeros_like(np.asarray(node_lon))
    return rasterize_to_grid(depth, node_lon, node_lat, grid.lon, grid.lat, triangles)


def _pad_u(u: np.ndarray) -> np.ndarray:
    ny, nx = u.shape
    out = np.zeros((ny, nx + 1), dtype=np.float32)
    out[:, :-1] = u.astype(np.float32)
    out[:, -1] = u[:, -1].astype(np.float32)
    return out


def _pad_v(v: np.ndarray) -> np.ndarray:
    ny, nx = v.shape
    out = np.zeros((ny + 1, nx), dtype=np.float32)
    out[:-1, :] = v.astype(np.float32)
    out[-1, :] = v[-1, :].astype(np.float32)
    return out


def _first_present(variables: dict, names: list[str]) -> str:
    for name in names:
        if name in variables:
            return name
    raise KeyError(
        f"none of {names} found in TELEMAC result variables: {list(variables)}"
    )
