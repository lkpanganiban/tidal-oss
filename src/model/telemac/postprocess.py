"""Convert TELEMAC Selafin results into the canonical screening outputs.

The web application and downstream analyses expect a fixed output contract
(``results.nc`` + a set of GeoTIFFs + a hotspot GeoJSON) produced by the
screening model.  This module reads the unstructured TELEMAC result file
(``r2d.slf``), rasterises the node fields onto a regular longitude/latitude
grid covering the refinement region, and writes exactly the same products so
the Flask/MapLibre stack is engine-agnostic.

Rasterisation uses scipy Delaunay + barycentric weights (with a nearest-node
fallback for target points outside the mesh footprint), so the routine never
hard-fails on minimal environments.
"""

from __future__ import annotations

import json
import os

import numpy as np

from .mesh import unproject_from_local_meters
from .selafin import read_serafin


def _target_grid(mesh_meta: dict, resolution_m: float):
    """Build the regular lon/lat raster grid for a refinement case output."""
    from model.grid import StructuredGrid

    bbox = mesh_meta["bbox"]
    lat0 = (
        mesh_meta["lat0"]
        if mesh_meta["coordinates_are_meters"]
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

    from .mesh import MeshRasterizer

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

    grid = _target_grid(mesh_meta, resolution_m)

    eta_name = _first_present(variables, ["ELEVATION Z", "ELEVATION", "FREE SURFACE"])
    u_name = _first_present(variables, ["VELOCITY U", "VELOCITY UX"])
    v_name = _first_present(variables, ["VELOCITY V", "VELOCITY VY"])

    # One geometry pass for all frames: Delaunay, barycentric weights, mesh
    # footprint mask and nearest-fallback tree are computed once (seconds)
    # instead of per frame (minutes at refinement-scale meshes).
    rast = MeshRasterizer(node_lon, node_lat, grid.lon, grid.lat, triangles)

    nt = times.shape[0]
    ny, nx = grid.lat.shape
    power_mean = np.zeros((ny, nx), dtype=np.float64)
    speed_max = np.zeros((ny, nx), dtype=np.float64)

    # The Python screening aggregates over its ~hourly snapshots rather than
    # every solver step, so we do the same here: keep ~360 evenly spaced frames
    # for both the persisted NetCDF time series AND the mean/max rasters.  This
    # keeps the TELEMAC output comparable to the Python one and avoids
    # rasterising tens of thousands of frames.
    _target_snapshots = 360
    _stride = max(1, nt // _target_snapshots)
    _frames = list(range(0, nt, _stride))
    _nframes = len(_frames)

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
        for t_idx in _frames:
            eta = rast.raster(variables[eta_name][t_idx])
            u = rast.raster(variables[u_name][t_idx]) if u_name else np.zeros_like(eta)
            v = rast.raster(variables[v_name][t_idx]) if v_name else np.zeros_like(eta)
            speed = np.sqrt(u**2 + v**2)
            power = 0.5 * rho * speed**3

            power_mean += np.nan_to_num(power)
            speed_max = np.maximum(speed_max, speed)

            u_pad = _pad_u(u)
            v_pad = _pad_v(v)
            writer.write_snapshot(times[t_idx], eta, u_pad, v_pad, power)

    power_mean = np.where(
        np.isfinite(power_mean), power_mean / max(_nframes, 1), np.nan
    )
    # `speed_max` already carries the triangle/land mask (NaN outside the mesh),
    # unlike `power_mean` which was NaN->0 accumulated above. Use it so the
    # power-density raster is not filled across the whole bounding box.
    grid.mask = np.isfinite(speed_max)
    grid.h = np.where(
        grid.mask,
        rast.raster(
            np.asarray(
                mesh_meta.get("node_depth") or np.zeros_like(node_lon), dtype=np.float64
            )
        ),
        np.nan,
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

    reconciliation = _write_reconciliation(
        out_dir,
        manifest,
        config,
        telemac_max_power=float(np.nanmax(power_mean)) if grid.mask.any() else 0.0,
        telemac_max_speed=float(np.nanmax(speed_max)) if grid.mask.any() else 0.0,
        region_id=region_id or manifest.get("region_id", ""),
    )

    return {
        "results_nc": nc_path,
        "tidal_power_density_tif": power_tif,
        "max_current_speed_tif": speed_tif,
        "bathymetry_tif": bathy_tif,
        "distance_to_coast_tif": dist_tif,
        "hotspots_geojson": geojson_path,
        "n_timesteps": nt,
        "max_power_Wm2": float(np.nanmax(power_mean)) if grid.mask.any() else 0.0,
        "reconciliation": reconciliation,
    }


def _read_window(tif_path: str, bbox: dict) -> np.ndarray | None:
    """Read a GeoTIFF window as a float64 array with nodata mapped to NaN.

    Returns ``None`` when the file is missing or the window is empty.
    """
    import rasterio
    from rasterio.windows import from_bounds

    if not os.path.isfile(tif_path):
        return None
    with rasterio.open(tif_path) as src:
        win = from_bounds(
            bbox["lon_min"],
            bbox["lat_min"],
            bbox["lon_max"],
            bbox["lat_max"],
            src.transform,
        )
        data = src.read(1, window=win).astype(np.float64)
        if src.nodata is not None:
            data[data == src.nodata] = np.nan
    if data.size == 0:
        return None
    return data


def _write_reconciliation(
    out_dir: str,
    manifest: dict,
    config: dict,
    *,
    telemac_max_power: float,
    telemac_max_speed: float,
    region_id: str,
) -> dict:
    """Compare the refined TELEMAC result against the screening parent.

    The nationwide screening products are the parent view: this samples the
    screening mean-power GeoTIFF inside the region bounding box and records
    both engines' statistics in ``reconciliation.json`` so zoom-in users can
    see how the refined estimate relates to the national one.
    """
    out_cfg = config.get("output", {})
    report: dict = {
        "region": region_id,
        "bbox": manifest.get("bbox"),
        "telemac_max_power_Wm2": telemac_max_power,
        "telemac_max_speed_mps": telemac_max_speed,
        "telemac_resolution_m": manifest.get("resolution_m"),
        "telemac_axis": manifest.get("axis"),
        "telemac_boundary_forcing": manifest.get("boundary_forcing"),
    }
    root_tif = os.path.join(
        out_cfg.get("dir", "output/"),
        out_cfg.get("final_geotiff", "tidal_power_density.tif"),
    )
    speed_tif = os.path.join(
        out_cfg.get("dir", "output/"),
        out_cfg.get("max_speed_geotiff", "max_current_speed.tif"),
    )
    if os.path.isfile(root_tif):
        try:
            bbox = manifest.get("bbox") or {}
            if bbox:
                data = _read_window(root_tif, bbox)
                if data is not None and np.isfinite(data).any():
                    s_max = float(np.nanmax(data))
                    s_mean = float(np.nanmean(data))
                    report["screening_max_power_Wm2"] = s_max
                    report["screening_mean_power_Wm2"] = s_mean
                    if s_max > 0:
                        report["ratio_telemac_to_screening"] = telemac_max_power / s_max
                sdata = _read_window(speed_tif, bbox)
                if sdata is not None and np.isfinite(sdata).any():
                    s_speed = float(np.nanmax(sdata))
                    report["screening_max_speed_mps"] = s_speed
                    report["screening_speed_p95_mps"] = float(
                        np.nanpercentile(sdata, 95)
                    )
                    report["screening_speed_median_mps"] = float(np.nanmedian(sdata))
                    if s_speed > 0:
                        report["speed_ratio_telemac_to_screening"] = (
                            telemac_max_speed / s_speed
                        )
        except Exception:
            pass

        # Distribution-level comparison on the child's own raster: max-vs-max
        # is dominated by the parent's coarse-grid jets; the bulk-field ratios
        # show how the two engines compare away from grid-scale extremes.
        try:
            import rasterio

            with rasterio.open(speed_tif) as r:
                c = r.read(1).astype(np.float64)
                if r.nodata is not None:
                    c[c == r.nodata] = np.nan
            cvalid = c[np.isfinite(c)]
            if cvalid.size:
                report["telemac_speed_p95_mps"] = float(np.percentile(cvalid, 95))
                report["telemac_speed_median_mps"] = float(np.median(cvalid))
                p95_s = report.get("screening_speed_p95_mps")
                med_s = report.get("screening_speed_median_mps")
                if p95_s:
                    report["p95_speed_ratio_telemac_to_screening"] = (
                        report["telemac_speed_p95_mps"] / p95_s
                    )
                if med_s:
                    report["median_speed_ratio_telemac_to_screening"] = (
                        report["telemac_speed_median_mps"] / med_s
                    )
        except Exception:
            pass

    # Acceptance test: speed within [0.7, 1.5]x of the parent is a pass,
    # within [0.35, 3.0]x tolerable (power is cubic in speed, so its windows
    # are the cubes of the speed windows); anything wider needs review.
    speed_ratio = report.get("speed_ratio_telemac_to_screening")
    power_ratio = report.get("ratio_telemac_to_screening")
    if speed_ratio:
        if 0.7 <= speed_ratio <= 1.5 and (not power_ratio or power_ratio >= 0.35):
            report["status"] = "ok"
        elif 0.35 <= speed_ratio <= 3.0:
            report["status"] = "tolerable"
        else:
            report["status"] = "review"
        report["note"] = (
            f"refined/parent speed ratio {speed_ratio:.2f}x; "
            "power scales with speed cubed"
        )
    try:
        with open(os.path.join(out_dir, "reconciliation.json"), "w") as f:
            json.dump(report, f, indent=2)
    except OSError:
        pass
    return report


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
