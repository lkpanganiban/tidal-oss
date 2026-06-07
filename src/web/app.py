"""Flask web service for tidal power density visualisation.

Serves:
- /                          MapLibre GL JS frontend
- /api/tiles/{z}/{x}/{y}     Raster tiles from the GeoTIFF (colormapped PNG)
- /api/query?lat=&lon=       Point query returning power-density value
- /api/metadata              Layer metadata (bounds, stats, colormap)
"""

from __future__ import annotations

import io
import json
import logging
import os
import struct
from pathlib import Path

import numpy as np
from flask import Flask, jsonify, request, send_file, send_from_directory

logger = logging.getLogger(__name__)

_WEB_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(_WEB_DIR, "static")
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "/output")
GEOTIFF_PATH = os.path.abspath(os.environ.get("GEOTIFF_PATH", os.path.join(OUTPUT_DIR, "tidal_power_density.tif")))

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="")

MAX_TILE_ZOOM = 10
TILE_SIZE = 256


def _open_raster():
    """Open the GeoTIFF lazily.  Returns None if the file does not exist."""
    try:
        import rasterio
    except ImportError:
        logger.error("rasterio not installed")
        return None
    if not os.path.isfile(GEOTIFF_PATH):
        logger.warning("GeoTIFF not found: %s", GEOTIFF_PATH)
        return None
    return rasterio.open(GEOTIFF_PATH)


def _render_tile(src, z: int, x: int, y: int) -> io.BytesIO | None:
    """Render a single 256×256 PNG tile from the source raster.

    Parameters
    ----------
    src : rasterio.DatasetReader
    z, x, y : int
        TMS tile coordinates.

    Returns
    -------
    BytesIO or None
        PNG image bytes, or None on error.
    """
    try:
        from PIL import Image
    except ImportError:
        logger.error("Pillow not installed")
        return None

    import rasterio
    from rasterio.warp import transform_bounds

    tms_y = (1 << z) - 1 - y

    west = x / (1 << z) * 360.0 - 180.0
    east = (x + 1) / (1 << z) * 360.0 - 180.0
    north = _mercator_to_lat(np.pi * (1.0 - 2.0 * y / (1 << z)))
    south = _mercator_to_lat(np.pi * (1.0 - 2.0 * (y + 1) / (1 << z)))

    bbox_src_crs = transform_bounds(
        "EPSG:4326", src.crs, west, south, east, north
    )
    window = src.window(*bbox_src_crs)

    if window.width < 1 or window.height < 1:
        return None

    data = src.read(1, window=window, out_shape=(TILE_SIZE, TILE_SIZE))
    data = np.ma.masked_invalid(data)

    if data.mask.all():
        return None

    rgba = _apply_colormap(data, src.nodata)

    buf = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buf, format="PNG")
    buf.seek(0)
    return buf


def _apply_colormap(
    data: np.ndarray, nodata: float | None
) -> np.ndarray:
    """Map a power-density array (W/m²) to RGBA using a perceptually
    uniform diverging colormap (blue → cyan → yellow → red).

    Returns uint8 array of shape (height, width, 4).
    """
    vmin, vmax = 0.0, 2000.0
    data = np.clip((data - vmin) / (vmax - vmin), 0.0, 1.0)

    cmap_stops = np.array([
        [0.0,  0.0,   0.0,   0.6,   1.0],   # transparent dark blue
        [0.1,  0.0,   0.3,   0.8,   1.0],   # blue
        [0.3,  0.0,   0.7,   0.8,   1.0],   # cyan
        [0.5,  0.0,   0.9,   0.5,   1.0],   # green
        [0.7,  0.9,   0.8,   0.0,   1.0],   # yellow
        [0.9,  1.0,   0.4,   0.0,   1.0],   # orange
        [1.0,  1.0,   0.0,   0.0,   1.0],   # red
    ])

    rgba = np.zeros((*data.shape, 4), dtype=np.uint8)
    for k in range(4):
        interp = np.interp(data, cmap_stops[:, 0], cmap_stops[:, k + 1])
        rgba[..., k] = (interp * 255).astype(np.uint8)

    if nodata is not None:
        is_nodata = np.ma.getmaskarray(data) if np.ma.is_masked(data) else np.zeros_like(data, dtype=bool)
        rgba[is_nodata, 3] = 0

    return rgba


def _mercator_to_lat(y: float) -> float:
    return np.rad2deg(2.0 * np.arctan(np.exp(y)) - np.pi / 2.0)


def _parse_path_geotiff() -> dict:
    """Check that a valid GeoTIFF exists and return metadata."""
    src = _open_raster()
    if src is None:
        return {"available": False, "geotiff_path": GEOTIFF_PATH}
    from rasterio.warp import transform_bounds

    bounds = src.bounds
    # Transform bounds to EPSG:4326 for the frontend
    if src.crs is not None and src.crs.to_epsg() != 4326:
        bbox_4326 = transform_bounds(src.crs, "EPSG:4326", bounds.left, bounds.bottom, bounds.right, bounds.top)
    else:
        bbox_4326 = (bounds.left, bounds.bottom, bounds.right, bounds.top)

    stats = _raster_stats(src)
    src.close()
    return {
        "available": True,
        "path": GEOTIFF_PATH,
        "bounds": {
            "west": bbox_4326[0],
            "south": bbox_4326[1],
            "east": bbox_4326[2],
            "north": bbox_4326[3],
        },
        "crs": "EPSG:4326",
        "units": "W/m2",
        "description": "Time-mean tidal-current power density",
        "stats": stats,
        "max_zoom": MAX_TILE_ZOOM,
    }


def _raster_stats(src) -> dict:
    data = src.read(1, masked=True)
    valid = data.compressed()
    if valid.size == 0:
        return {"min": 0, "max": 0, "mean": 0, "p95": 0}
    return {
        "min": float(valid.min()),
        "max": float(valid.max()),
        "mean": float(valid.mean()),
        "p95": float(np.percentile(valid, 95)),
    }


def _point_query(lat: float, lon: float) -> dict | None:
    """Query the raster at a geographic point."""
    src = _open_raster()
    if src is None:
        return None

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

    return {"lat": lat, "lon": lon, "power_density_Wm2": round(v, 2)}


# ---- Routes -------------------------------------------------------------


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/metadata")
def metadata():
    return jsonify(_parse_path_geotiff())


@app.route("/api/query")
def query():
    lat_str = request.args.get("lat")
    lon_str = request.args.get("lon")
    if lat_str is None or lon_str is None:
        return jsonify({"error": "lat and lon required"}), 400
    try:
        lat = float(lat_str)
        lon = float(lon_str)
    except ValueError:
        return jsonify({"error": "invalid lat/lon"}), 400

    result = _point_query(lat, lon)
    if result is None:
        return jsonify({"error": "no data at this location"}), 404
    return jsonify(result)


@app.route("/api/tiles/<int:z>/<int:x>/<int:y>.png")
def tile(z: int, x: int, y: int):
    if z > MAX_TILE_ZOOM:
        return "", 204

    src = _open_raster()
    if src is None:
        return "", 404

    try:
        buf = _render_tile(src, z, x, y)
    finally:
        src.close()

    if buf is None:
        return "", 204

    return send_file(buf, mimetype="image/png")


@app.route("/api/download/tidal_power_density.tif")
def download_geotiff():
    if not os.path.isfile(GEOTIFF_PATH):
        return jsonify({"error": "GeoTIFF not yet generated"}), 404
    return send_file(
        GEOTIFF_PATH,
        mimetype="image/tiff",
        as_attachment=True,
        download_name="tidal_power_density.tif",
    )


def main():
    global GEOTIFF_PATH

    import argparse

    parser = argparse.ArgumentParser(description="Tidal web service")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--geotiff", default=GEOTIFF_PATH, help="Path to GeoTIFF")
    args = parser.parse_args()

    GEOTIFF_PATH = os.path.abspath(args.geotiff)
    os.environ["GEOTIFF_PATH"] = GEOTIFF_PATH

    logging.basicConfig(level=logging.INFO)
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
