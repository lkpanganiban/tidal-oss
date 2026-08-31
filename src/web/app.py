"""Flask web service — marine spatial planning (MSP) interface for tidal energy.

Serves:
- /                          MapLibre GL JS frontend
- /api/layers                Metadata for all available raster layers
- /api/tiles/{layer}/{z}/{x}/{y}.png   Colormapped raster tiles
- /api/tiles/{z}/{x}/{y}.png           Alias for the power layer
- /api/query?lat=&lon=&layer= Point query (power | speed | depth | distance)
- /api/timeseries?lat=&lon=  Tidal elevation / current time series from results.nc
- /api/hotspots?min=&limit=  Ranked hotspot sites (GeoJSON)
- /api/area_stats            POST polygon → resource statistics within it
- /api/resource              Filtered-domain resource totals (AEP, MW)
- /api/download/{file}       GeoTIFF downloads
"""

from __future__ import annotations

import io
import json
import logging
import os
import threading
from functools import lru_cache
from typing import Any

import numpy as np
from flask import Flask, jsonify, request, send_file, send_from_directory

logger = logging.getLogger(__name__)

_WEB_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(_WEB_DIR, "static")
OUTPUT_DIR = os.path.abspath(os.environ.get("OUTPUT_DIR", "output"))
GEOTIFF_PATH = os.path.abspath(
    os.environ.get("GEOTIFF_PATH", os.path.join(OUTPUT_DIR, "tidal_power_density.tif"))
)

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="")

# netCDF4 is not thread-safe: concurrent opens of the same file segfault the
# process.  The threaded web server fires parallel timeseries requests, so all
# access to results.nc must be serialised.
_NETCDF_LOCK = threading.Lock()

MAX_TILE_ZOOM = 10
TILE_SIZE = 256
DEFAULT_EFFICIENCY = 0.4  # tidal turbine array extraction efficiency

# ---------------------------------------------------------------------------
# Layer registry
# ---------------------------------------------------------------------------

# Colormap stops: rows of [position, r, g, b, a] in 0..1 (a = 0..1).
POWER_CMAP = np.array(
    [
        [0.0, 0.0, 0.0, 0.6, 1.0],  # transparent dark blue
        [0.1, 0.0, 0.3, 0.8, 1.0],  # blue
        [0.3, 0.0, 0.7, 0.8, 1.0],  # cyan
        [0.5, 0.0, 0.9, 0.5, 1.0],  # green
        [0.7, 0.9, 0.8, 0.0, 1.0],  # yellow
        [0.9, 1.0, 0.4, 0.0, 1.0],  # orange
        [1.0, 1.0, 0.0, 0.0, 1.0],  # red
    ]
)

SPEED_CMAP = np.array(
    [
        [0.0, 0.27, 0.0, 0.33, 1.0],  # dark violet
        [0.25, 0.13, 0.35, 0.55, 1.0],  # purple
        [0.5, 0.1, 0.55, 0.55, 1.0],  # teal
        [0.75, 0.35, 0.72, 0.35, 1.0],  # green
        [1.0, 0.99, 0.9, 0.15, 1.0],  # yellow
    ]
)

DEPTH_CMAP = np.array(
    [
        [0.0, 0.0, 0.75, 1.0, 1.0],  # shallow cyan
        [0.25, 0.1, 0.55, 0.9, 1.0],  # light blue
        [0.5, 0.1, 0.32, 0.72, 1.0],  # mid blue
        [0.75, 0.06, 0.12, 0.42, 1.0],  # deep blue
        [1.0, 0.02, 0.02, 0.15, 1.0],  # abyssal navy
    ]
)

DISTANCE_CMAP = np.array(
    [
        [0.0, 0.0, 0.0, 0.4, 1.0],  # dark
        [0.3, 0.4, 0.0, 0.6, 1.0],  # purple
        [0.6, 0.8, 0.2, 0.5, 1.0],  # pink
        [1.0, 1.0, 0.9, 0.2, 1.0],  # bright yellow
    ]
)


def _legend_stops(vmin: float, vmax: float, n: int = 5) -> list[list[float]]:
    """Evenly spaced legend stops between vmin and vmax."""
    return [[round(vmin + (vmax - vmin) * k / (n - 1), 1) for k in range(n)]]


LAYERS: dict[str, dict] = {
    "power": {
        "file": "tidal_power_density.tif",
        "label": "Mean power density",
        "units": "W/m²",
        "description": "Time-mean tidal-current power density",
        "vmin": 0.0,
        "vmax": 2000.0,
        "cmap": POWER_CMAP,
    },
    "speed": {
        "file": "max_current_speed.tif",
        "label": "Max current speed",
        "units": "m/s",
        "description": "Maximum depth-averaged current speed over the run",
        "vmin": 0.0,
        "vmax": 3.0,
        "cmap": SPEED_CMAP,
    },
    "depth": {
        "file": "bathymetry.tif",
        "label": "Bathymetry",
        "units": "m",
        "description": "Bathymetric depth (positive down)",
        "vmin": 0.0,
        "vmax": 200.0,
        "cmap": DEPTH_CMAP,
    },
    "distance": {
        "file": "distance_to_coast.tif",
        "label": "Distance to coast",
        "units": "km",
        "description": "Distance to the nearest coast",
        "vmin": 0.0,
        "vmax": 100.0,
        "cmap": DISTANCE_CMAP,
    },
}


# Allow per-layer value-range overrides via environment variables
# (e.g. TIDAL_POWER_VMAX=1.0) so low-amplitude refinement outputs stay
# legible.  Defaults are unchanged when the variables are unset.
for _name in LAYERS:
    _env_vmax = os.environ.get(f"TIDAL_{_name.upper()}_VMAX")
    if _env_vmax:
        try:
            LAYERS[_name]["vmax"] = float(_env_vmax)
        except ValueError:
            logger.warning(
                "Ignoring invalid TIDAL_%s_VMAX=%s", _name.upper(), _env_vmax
            )


def _resolve_root(region: str | None) -> str:
    """Directory holding a dataset's outputs.

    With no region the Python screening outputs in ``OUTPUT_DIR`` are used;
    otherwise the per-region TELEMAC-2D refinement under
    ``OUTPUT_DIR/telemac/<region>/`` is used (when it exists).
    """
    if region:
        cand = os.path.join(OUTPUT_DIR, "telemac", region)
        if os.path.isdir(cand):
            return cand
    return os.path.dirname(GEOTIFF_PATH)


def _layer_path(layer: str, region: str | None = None) -> str:
    """Absolute path of a layer's GeoTIFF within the selected dataset."""
    return os.path.join(_resolve_root(region), LAYERS[layer]["file"])


def _results_nc_path(region: str | None = None) -> str:
    return os.path.join(_resolve_root(region), "results.nc")


def _hotspots_path(region: str | None = None) -> str:
    return os.path.join(_resolve_root(region), "hotspots.geojson")


def _bounds_dict(src) -> dict:
    """Bounding box (EPSG:4326) of an open raster source as a dict."""
    from rasterio.warp import transform_bounds

    b = src.bounds
    if src.crs is not None and src.crs.to_epsg() != 4326:
        bb = transform_bounds(src.crs, "EPSG:4326", b.left, b.bottom, b.right, b.top)
    else:
        bb = (b.left, b.bottom, b.right, b.top)
    return {"west": bb[0], "south": bb[1], "east": bb[2], "north": bb[3]}


def _root_bounds(root: str) -> dict | None:
    """Bounding box (EPSG:4326) of a dataset's power raster, or None."""
    src = _open_raster(os.path.join(root, LAYERS["power"]["file"]))
    if src is None:
        return None
    try:
        return _bounds_dict(src)
    finally:
        src.close()


# ---------------------------------------------------------------------------
# Raster helpers
# ---------------------------------------------------------------------------


def _open_raster(path: str = GEOTIFF_PATH):
    """Open a GeoTIFF lazily.  Returns None if the file does not exist."""
    try:
        import rasterio
    except ImportError:
        logger.error("rasterio not installed")
        return None
    if not os.path.isfile(path):
        return None
    return rasterio.open(path)


def _file_mtime(path: str) -> float:
    """Modification time of a file (cache-invalidation key)."""
    try:
        return os.path.getmtime(path)
    except OSError:
        return -1.0


@lru_cache(maxsize=1024)
def _render_tile_cached(
    layer: str, z: int, x: int, y: int, mtime: float, region: str | None = None
) -> bytes | None:
    """Render a tile to PNG bytes, cached keyed on (layer, z, x, y, mtime)."""
    path = _layer_path(layer, region)
    src = _open_raster(path)
    if src is None:
        return None
    try:
        buf = _render_tile(src, z, x, y, layer)
    finally:
        src.close()
    if buf is None:
        return None
    return buf.getvalue()


def _render_tile(src, z: int, x: int, y: int, layer: str) -> io.BytesIO | None:
    """Render a single 256×256 PNG tile from a source raster."""
    try:
        from PIL import Image
    except ImportError:
        logger.error("Pillow not installed")
        return None

    from rasterio.enums import Resampling
    from rasterio.transform import from_bounds
    from rasterio.warp import reproject, transform_bounds

    west = x / (1 << z) * 360.0 - 180.0
    east = (x + 1) / (1 << z) * 360.0 - 180.0
    north = _mercator_to_lat(np.pi * (1.0 - 2.0 * y / (1 << z)))
    south = _mercator_to_lat(np.pi * (1.0 - 2.0 * (y + 1) / (1 << z)))

    # Reproject into the complete Web-Mercator tile. Reading only the source
    # intersection and resizing it to 256x256 stretches small rasters across
    # the whole tile, misaligning them with GeoJSON overlays.
    west_m, south_m, east_m, north_m = transform_bounds(
        "EPSG:4326", "EPSG:3857", west, south, east, north
    )
    dst_transform = from_bounds(west_m, south_m, east_m, north_m, TILE_SIZE, TILE_SIZE)
    data = np.full((TILE_SIZE, TILE_SIZE), np.nan, dtype=np.float32)
    reproject(
        source=src.read(1),
        destination=data,
        src_transform=src.transform,
        src_crs=src.crs,
        src_nodata=src.nodata if src.nodata is not None else np.nan,
        dst_transform=dst_transform,
        dst_crs="EPSG:3857",
        dst_nodata=np.nan,
        resampling=Resampling.bilinear,
    )
    data = np.ma.masked_invalid(data)

    if data.mask.all():
        return None

    meta = LAYERS[layer]
    rgba = _apply_colormap(
        data,
        src.nodata,
        cmap_stops=meta["cmap"],
        vmin=meta["vmin"],
        vmax=meta["vmax"],
    )

    buf = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buf, format="PNG")
    buf.seek(0)
    return buf


def _apply_colormap(
    data: np.ndarray,
    nodata: float | None,
    cmap_stops: np.ndarray,
    vmin: float,
    vmax: float,
) -> np.ndarray:
    """Map an array to RGBA using piecewise-linear colormap stops.

    Invalid cells (NaN / nodata) are made fully transparent.
    Returns uint8 array of shape (height, width, 4).
    """
    is_masked = np.ma.is_masked(data)
    raw = np.asarray(data)
    invalid = np.isnan(raw) if not is_masked else np.ma.getmaskarray(data)
    if nodata is not None:
        invalid |= raw == nodata

    values = np.where(invalid, 0.0, raw)
    t = np.clip((values - vmin) / (vmax - vmin), 0.0, 1.0)

    rgba = np.zeros((*t.shape, 4), dtype=np.uint8)
    for k in range(4):
        interp = np.interp(t, cmap_stops[:, 0], cmap_stops[:, k + 1])
        rgba[..., k] = (interp * 255).astype(np.uint8)

    rgba[invalid, 3] = 0
    return rgba


def _mercator_to_lat(y: float) -> float:
    return np.rad2deg(2.0 * np.arctan(np.exp(y)) - np.pi / 2.0)


def _layer_metadata(layer: str, region: str | None = None) -> dict | None:
    """Per-layer metadata dict, or None when the file is unavailable."""
    meta = LAYERS[layer]
    path = _layer_path(layer, region)
    src = _open_raster(path)
    if src is None:
        return None
    try:
        bounds = _bounds_dict(src)
        stats = _raster_stats(src)
    finally:
        src.close()

    return {
        "file": meta["file"],
        "label": meta["label"],
        "units": meta["units"],
        "description": meta["description"],
        "bounds": bounds,
        "crs": "EPSG:4326",
        "stats": stats,
        "vmin": meta["vmin"],
        "vmax": meta["vmax"],
        "legend": _legend_stops(meta["vmin"], meta["vmax"]),
        "max_zoom": MAX_TILE_ZOOM,
    }


def _raster_stats(src) -> dict:
    data = np.ma.masked_invalid(src.read(1, masked=True))
    valid = data.compressed()
    if valid.size == 0:
        return {"min": 0, "max": 0, "mean": 0, "p95": 0}
    return {
        "min": float(valid.min()),
        "max": float(valid.max()),
        "mean": float(valid.mean()),
        "p95": float(np.percentile(valid, 95)),
    }


def _point_query(
    lat: float, lon: float, layer: str = "power", region: str | None = None
) -> dict | None:
    """Query a raster layer at a geographic point."""
    path = _layer_path(layer, region)
    src = _open_raster(path)
    if src is None:
        return None

    try:
        from rasterio.transform import rowcol
        from rasterio.warp import transform

        try:
            if src.crs is not None and src.crs.to_epsg() != 4326:
                x, y = transform("EPSG:4326", src.crs, [lon], [lat])
                row, col = rowcol(src.transform, x[0], y[0])
            else:
                row, col = rowcol(src.transform, lon, lat)
        except Exception:
            return None

        if not (0 <= row < src.height and 0 <= col < src.width):
            return None

        value = src.read(1, window=((row, row + 1), (col, col + 1)))
        if value.size == 0:
            return None

        v = float(value[0, 0])
        if src.nodata is not None and v == src.nodata:
            return None
        if np.isnan(v):
            return None
    finally:
        src.close()

    return {"lat": lat, "lon": lon, "layer": layer, "value": round(v, 3)}


def _cell_area_m2(lat_deg: float, res_deg_x: float, res_deg_y: float) -> float:
    """Approximate cell area in m² (degrees → metres with cos(lat) correction)."""
    m_per_deg = 111320.0
    return (
        (res_deg_x * m_per_deg) * (res_deg_y * m_per_deg) * np.cos(np.deg2rad(lat_deg))
    )


def _read_layer_array(
    layer: str, region: str | None = None
) -> tuple[np.ndarray | None, Any, int, int]:
    """Read a layer as (array, transform, width, height) or (None, ...) if missing."""
    path = _layer_path(layer, region)
    src = _open_raster(path)
    if src is None:
        return None, 0.0, 0, 0
    try:
        return src.read(1), src.transform, src.width, src.height
    finally:
        src.close()


# ---------------------------------------------------------------------------
# Resource / MSP calculations
# ---------------------------------------------------------------------------


def _resource_summary(
    mask: np.ndarray, power: np.ndarray, transform, efficiency: float
) -> dict:
    """Aggregate resource statistics for the cells selected by *mask*.

    Shared by :func:`_resource_totals` and :func:`_area_stats`: cell count,
    area (cos(lat)-corrected), mean/max/p95 power density, and gross /
    extractable / annual energy.  Callers guard the empty-mask case themselves
    and may add layer-specific fields (e.g. ``depth_range_m``).
    """
    n = int(mask.sum())
    res_x = transform.a
    res_y = -transform.e

    # Area via cell counts with cos(lat) correction on the mask centroid
    rows, cols = np.where(mask)
    lat_c = transform.f + (rows + 0.5) * transform.e
    cell_area = _cell_area_m2(float(np.mean(lat_c)), res_x, res_y)

    sel = power[mask]
    mean_pd = float(np.mean(sel))
    area_m2 = n * cell_area
    gross_w = float(np.sum(sel) * cell_area)

    return {
        "n_cells": n,
        "area_km2": area_m2 / 1e6,
        "mean_power_density": round(mean_pd, 2),
        "max_power_density": round(float(np.max(sel)), 2),
        "p95_power_density": round(float(np.percentile(sel, 95)), 2),
        "gross_mw": round(gross_w / 1e6, 3),
        "extractable_mw": round(gross_w * efficiency / 1e6, 3),
        "aep_gwh_yr": round(gross_w * efficiency * 8760.0 / 1e9, 3),
    }


def _resource_totals(
    min_power: float,
    depth_min: float | None,
    depth_max: float | None,
    efficiency: float,
    region: str | None = None,
) -> dict | None:
    """Aggregate resource statistics over the filtered domain."""
    power, transform, w, h = _read_layer_array("power", region)
    if power is None:
        return None

    valid = ~(np.isnan(power) | (power <= 0))
    mask = valid & (power >= min_power)

    depth = None
    if depth_min is not None or depth_max is not None:
        depth, _, _, _ = _read_layer_array("depth", region)
        if depth is not None:
            if depth_min is not None:
                mask &= depth >= depth_min
            if depth_max is not None:
                mask &= depth <= depth_max

    if int(mask.sum()) == 0:
        return {
            "n_cells": 0,
            "area_km2": 0.0,
            "mean_power_density": 0.0,
            "gross_mw": 0.0,
            "extractable_mw": 0.0,
            "aep_gwh_yr": 0.0,
        }

    return _resource_summary(mask, power, transform, efficiency)


@lru_cache(maxsize=64)
def _resource_cached(
    min_power: float,
    depth_min: float,
    depth_max: float,
    efficiency: float,
    mtime: float,
    region: str | None = None,
) -> dict | None:
    return _resource_totals(
        min_power, depth_min or None, depth_max or None, efficiency, region
    )


def _area_stats(
    polygon: list[list[float]], efficiency: float, region: str | None = None
) -> dict | None:
    """Statistics for cells inside a polygon (GeoJSON ring of [lon, lat])."""
    power, transform, w, h = _read_layer_array("power", region)
    if power is None:
        return None

    from rasterio.features import geometry_mask
    from rasterio.warp import transform_geom

    src = _open_raster(_layer_path("power", region))
    if src is None:
        return None
    try:
        src_crs = src.crs
    finally:
        src.close()

    ring = list(polygon) + [list(polygon[0])]
    geom = {"type": "Polygon", "coordinates": [ring]}
    if src_crs is not None and src_crs.to_epsg() != 4326:
        geom = transform_geom("EPSG:4326", src_crs, geom)

    inside = geometry_mask([geom], out_shape=(h, w), transform=transform, invert=True)
    valid = ~(np.isnan(power) | (power <= 0))
    mask = inside & valid

    if int(mask.sum()) == 0:
        return {
            "n_cells": 0,
            "area_km2": 0.0,
            "mean_power_density": 0.0,
            "gross_mw": 0.0,
            "extractable_mw": 0.0,
            "aep_gwh_yr": 0.0,
        }

    summary = _resource_summary(mask, power, transform, efficiency)
    summary["area_km2"] = round(summary["area_km2"], 3)

    # Depth range inside the polygon (when available)
    depth_range = None
    depth, _, _, _ = _read_layer_array("depth", region)
    if depth is not None and np.any(inside & ~np.isnan(depth)):
        dv = depth[inside & ~np.isnan(depth)]
        depth_range = [round(float(dv.min()), 1), round(float(dv.max()), 1)]
    summary["depth_range_m"] = depth_range

    return summary


@lru_cache(maxsize=32)
def _area_stats_cached(
    ring_json: str, efficiency: float, mtime: float, region: str | None = None
) -> dict | None:
    return _area_stats(json.loads(ring_json), efficiency, region)


def _timeseries(lat: float, lon: float, region: str | None = None) -> dict | None:
    """Nearest-cell time series from results.nc."""
    try:
        from netCDF4 import Dataset
    except ImportError:
        return None

    path = _results_nc_path(region)
    if not os.path.isfile(path):
        return None

    with _NETCDF_LOCK, Dataset(path, "r") as nc:
        lat_arr = np.asarray(nc["lat"][:])
        lon_arr = np.asarray(nc["lon"][:])
        d2 = (lat_arr - lat) ** 2 + (lon_arr - lon) ** 2
        row, col = np.unravel_index(int(np.argmin(d2)), lat_arr.shape)

        times = np.asarray(nc["time"][:], dtype=np.float64)
        eta = np.asarray(nc["eta"][:, row, col], dtype=np.float64)
        u = np.asarray(nc["u"][:, row, :], dtype=np.float64)
        v = np.asarray(nc["v"][:, :, col], dtype=np.float64)
        power = np.asarray(nc["power_density"][:, row, col], dtype=np.float64)

    # Cell-centre speed from edge velocities
    u_c = 0.5 * (u[:, col] + u[:, col + 1]) if col + 1 < u.shape[1] else u[:, col]
    v_c = 0.5 * (v[:, row] + v[:, row + 1]) if row + 1 < v.shape[1] else v[:, row]
    speed_ts = np.sqrt(u_c**2 + v_c**2)

    return {
        "lat": float(lat_arr[row, col]),
        "lon": float(lon_arr[row, col]),
        "time_hours": [round(float(t) / 3600.0, 3) for t in times],
        "eta_m": [round(float(x), 3) for x in eta],
        "speed_mps": [round(float(x), 3) for x in speed_ts],
        "power_wm2": [round(float(x), 2) for x in power],
        "summary": {
            "max_speed_mps": round(float(np.max(speed_ts)), 2),
            "mean_speed_mps": round(float(np.mean(speed_ts)), 2),
            "max_eta_m": round(float(np.max(np.abs(eta))), 2),
            "mean_power_wm2": round(float(np.mean(power)), 2),
            "n_points": int(len(times)),
        },
    }


@lru_cache(maxsize=256)
def _timeseries_cached(
    lat: float, lon: float, mtime: float, region: str | None = None
) -> dict | None:
    return _timeseries(lat, lon, region)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/layers")
def layers():
    """Metadata for every configured layer (available or not)."""
    region = request.args.get("region")
    out = {}
    for name in LAYERS:
        meta = _layer_metadata(name, region)
        if meta is not None:
            meta["available"] = True
        else:
            meta = {
                "label": LAYERS[name]["label"],
                "units": LAYERS[name]["units"],
                "available": False,
            }
        out[name] = meta
    resp = jsonify(
        {
            "layers": out,
            "results_nc": os.path.isfile(_results_nc_path(region)),
            "region": region or "",
        }
    )
    resp.headers["Cache-Control"] = "public, max-age=300"
    return resp


@app.route("/api/metadata")
def metadata():
    """Backwards-compatible metadata alias for the power layer."""
    meta = _layer_metadata("power", request.args.get("region"))
    if meta is not None:
        meta["available"] = True
    else:
        meta = {"available": False}
    resp = jsonify(meta)
    resp.headers["Cache-Control"] = "public, max-age=300"
    return resp


@app.route("/api/datasets")
def datasets():
    """List every servable dataset: the Python screening + TELEMAC-2D regions."""
    items = []
    root_bounds = _root_bounds(os.path.dirname(GEOTIFF_PATH))
    items.append(
        {
            "id": "",
            "label": "Python screening (archipelago)",
            "engine": "python",
            "bounds": root_bounds,
        }
    )
    telemac_dir = os.path.join(OUTPUT_DIR, "telemac")
    if os.path.isdir(telemac_dir):
        for name in sorted(os.listdir(telemac_dir)):
            d = os.path.join(telemac_dir, name)
            if os.path.isdir(d) and os.path.isfile(
                os.path.join(d, LAYERS["power"]["file"])
            ):
                items.append(
                    {
                        "id": name,
                        "label": f"TELEMAC-2D · {name}",
                        "engine": "telemac2d",
                        "bounds": _root_bounds(d),
                    }
                )
    resp = jsonify({"datasets": items})
    resp.headers["Cache-Control"] = "public, max-age=300"
    return resp


@app.route("/api/query")
def query():
    lat_str = request.args.get("lat")
    lon_str = request.args.get("lon")
    layer = request.args.get("layer", "power")
    if layer not in LAYERS:
        return jsonify({"error": f"unknown layer: {layer}"}), 400
    if lat_str is None or lon_str is None:
        return jsonify({"error": "lat and lon required"}), 400
    try:
        lat = float(lat_str)
        lon = float(lon_str)
    except ValueError:
        return jsonify({"error": "invalid lat/lon"}), 400

    result = _point_query(lat, lon, layer, request.args.get("region"))
    if result is None:
        return jsonify({"error": "no data at this location"}), 404
    return jsonify(result)


@app.route("/api/tiles/<int:z>/<int:x>/<int:y>.png")
@app.route("/api/tiles/<layer>/<int:z>/<int:x>/<int:y>.png")
def tile(layer: str = "power", z: int = 0, x: int = 0, y: int = 0):
    if z < 0 or z > MAX_TILE_ZOOM:
        return "", 204
    n = 1 << z
    if not (0 <= x < n and 0 <= y < n):
        return jsonify({"error": "tile out of range"}), 404
    if layer not in LAYERS:
        return jsonify({"error": f"unknown layer: {layer}"}), 404
    region = request.args.get("region")
    if not os.path.isfile(_layer_path(layer, region)):
        return jsonify({"error": f"layer '{layer}' not generated"}), 404

    try:
        tile_bytes = _render_tile_cached(
            layer, z, x, y, _file_mtime(_layer_path(layer, region)), region
        )
    except Exception as exc:
        logger.exception(
            "Tile render failed (layer=%s z=%d x=%d y=%d): %s", layer, z, x, y, exc
        )
        return jsonify({"error": "tile render failed"}), 500

    if tile_bytes is None:
        return "", 204

    resp = send_file(io.BytesIO(tile_bytes), mimetype="image/png")
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


@app.route("/api/timeseries")
def timeseries():
    lat_str = request.args.get("lat")
    lon_str = request.args.get("lon")
    if lat_str is None or lon_str is None:
        return jsonify({"error": "lat and lon required"}), 400
    try:
        lat = float(lat_str)
        lon = float(lon_str)
    except ValueError:
        return jsonify({"error": "invalid lat/lon"}), 400

    region = request.args.get("region")
    result = _timeseries_cached(lat, lon, _file_mtime(_results_nc_path(region)), region)
    if result is None:
        return jsonify({"error": "no time series available (run the model first)"}), 404
    return jsonify(result)


@app.route("/api/turbines")
def turbines():
    """The sample set of the world's top tidal in-stream turbines."""
    from .turbines import all_turbine_specs

    return jsonify({"turbines": all_turbine_specs()})


@app.route("/api/turbine_performance")
def turbine_performance():
    """Simulate every turbine at a site using the model's speed time series."""
    from .turbines import all_performance

    lat_str = request.args.get("lat")
    lon_str = request.args.get("lon")
    if lat_str is None or lon_str is None:
        return jsonify({"error": "lat and lon required"}), 400
    try:
        lat = float(lat_str)
        lon = float(lon_str)
    except ValueError:
        return jsonify({"error": "invalid lat/lon"}), 400

    region = request.args.get("region")
    ts = _timeseries_cached(lat, lon, _file_mtime(_results_nc_path(region)), region)
    if ts is None:
        return jsonify({"error": "no time series available (run the model first)"}), 404

    perf = all_performance(ts["speed_mps"], ts["time_hours"])
    return jsonify(
        {
            "lat": ts["lat"],
            "lon": ts["lon"],
            "window_hours": round(ts["time_hours"][-1] - ts["time_hours"][0], 3)
            if len(ts["time_hours"]) >= 2
            else 0.0,
            "site_summary": ts["summary"],
            "turbines": perf,
        }
    )


@app.route("/api/hotspots")
def hotspots():
    path = _hotspots_path(request.args.get("region"))
    if not os.path.isfile(path):
        return jsonify(
            {"error": "hotspots.geojson not found (run the model first)"}
        ), 404

    try:
        with open(path) as f:
            fc = json.load(f)
    except Exception as exc:
        logger.exception("Failed to read hotspots: %s", exc)
        return jsonify({"error": "failed to read hotspots"}), 500

    min_power = request.args.get("min", type=float)
    limit = request.args.get("limit", type=int)

    features = fc.get("features", [])
    if min_power is not None:
        features = [
            f
            for f in features
            if f.get("properties", {}).get("power_density_Wm2", 0) >= min_power
        ]
    features.sort(
        key=lambda f: f.get("properties", {}).get("power_density_Wm2", 0.0),
        reverse=True,
    )
    if limit is not None and limit > 0:
        features = features[:limit]

    return jsonify({"type": "FeatureCollection", "features": features})


@app.route("/api/area_stats", methods=["POST"])
def area_stats():
    """POST {"polygon": [[lon, lat], ...], "efficiency": 0.4} → stats."""
    body = request.get_json(silent=True)
    if not body or "polygon" not in body:
        return jsonify({"error": "JSON body with 'polygon' required"}), 400
    polygon = body["polygon"]
    if len(polygon) < 3:
        return jsonify({"error": "polygon needs at least 3 points"}), 400
    efficiency = float(body.get("efficiency", DEFAULT_EFFICIENCY))
    if not (0 < efficiency <= 1):
        return jsonify({"error": "efficiency must be in (0, 1]"}), 400

    region = request.args.get("region")
    result = _area_stats_cached(
        json.dumps([[float(a), float(b)] for a, b in polygon]),
        efficiency,
        _file_mtime(_layer_path("power", region)),
        region,
    )
    if result is None:
        return jsonify({"error": "power layer not available"}), 404
    return jsonify(result)


@app.route("/api/resource")
def resource():
    """GET /api/resource?min_power=&depth_min=&depth_max=&efficiency= → totals."""
    min_power = request.args.get("min_power", default=200.0, type=float)
    depth_min = request.args.get("depth_min", type=float)
    depth_max = request.args.get("depth_max", type=float)
    efficiency = request.args.get("efficiency", default=DEFAULT_EFFICIENCY, type=float)

    if min_power < 0:
        return jsonify({"error": "min_power must be >= 0"}), 400
    if depth_min is not None and depth_max is not None and depth_min > depth_max:
        return jsonify({"error": "depth_min must be <= depth_max"}), 400
    if not (0 < efficiency <= 1):
        return jsonify({"error": "efficiency must be in (0, 1]"}), 400

    region = request.args.get("region")
    result = _resource_cached(
        min_power,
        depth_min or 0.0,
        depth_max or 0.0,
        efficiency,
        _file_mtime(_layer_path("power", region)),
        region,
    )
    if result is None:
        return jsonify({"error": "power layer not available"}), 404
    return jsonify(result)


@app.route("/api/download/<path:filename>")
def download(filename: str):
    """Download a model output file (GeoTIFF layers or hotspots GeoJSON)."""
    safe_names = {meta["file"] for meta in LAYERS.values()} | {
        "hotspots.geojson",
        "results.nc",
    }
    if filename not in safe_names:
        return jsonify({"error": "file not available for download"}), 404

    path = os.path.join(_resolve_root(request.args.get("region")), filename)
    if not os.path.isfile(path):
        return jsonify({"error": f"{filename} not yet generated"}), 404

    mime = (
        "image/tiff"
        if filename.endswith(".tif")
        else "application/json"
        if filename.endswith(".geojson")
        else "application/x-netcdf"
    )
    return send_file(path, mimetype=mime, as_attachment=True, download_name=filename)


def main():
    global GEOTIFF_PATH

    import argparse

    parser = argparse.ArgumentParser(description="Tidal web service")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--geotiff", default=GEOTIFF_PATH, help="Path to power GeoTIFF")
    args = parser.parse_args()

    GEOTIFF_PATH = os.path.abspath(args.geotiff)
    os.environ["GEOTIFF_PATH"] = GEOTIFF_PATH

    logging.basicConfig(level=logging.INFO)
    # threaded=True: the map UI fires many concurrent tile/query requests;
    # the single-threaded default drops connections under that load.
    # (gunicorn, used by docker compose, is the production server.)
    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)


if __name__ == "__main__":
    main()
