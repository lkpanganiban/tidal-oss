"""Flask REST API for the tidal-current energy web service."""

import json
import os
from pathlib import Path

from flask import Flask, jsonify, request, send_file, abort
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "/data"))
GEOSERVER_URL = os.environ.get("GEOSERVER_URL", "http://localhost:8080/geoserver")

LAYERS = [
    {
        "id": "tidal_power_density",
        "name": "Tidal Current Power Density",
        "description": "Time-averaged tidal-current power density (W/m²) "
                       "computed from Thetis 2D shallow-water simulation.",
        "units": "W/m²",
        "file": "tidal_power_density.tif",
        "geoserver_workspace": "phil_tidal_energy",
        "geoserver_layer": "tidal_power_density",
    }
]


@app.route("/api/layers", methods=["GET"])
def list_layers():
    """List available tidal-energy layers with metadata."""
    result = []
    for layer in LAYERS:
        tif_path = OUTPUT_DIR / layer["file"]
        entry = {
            "id": layer["id"],
            "name": layer["name"],
            "description": layer["description"],
            "units": layer["units"],
            "available": tif_path.exists(),
            "filesize_mb": round(tif_path.stat().st_size / (1024 * 1024), 2)
            if tif_path.exists() else None,
            "wms_url": f"{GEOSERVER_URL}/{layer['geoserver_workspace']}/wms",
            "wmts_url": f"{GEOSERVER_URL}/gwc/service/wmts",
            "layer_name": f"{layer['geoserver_workspace']}:{layer['geoserver_layer']}",
        }
        result.append(entry)
    return jsonify(result)


@app.route("/api/layers/<layer_id>", methods=["GET"])
def get_layer(layer_id):
    """Get detailed metadata for a specific layer."""
    for layer in LAYERS:
        if layer["id"] == layer_id:
            tif_path = OUTPUT_DIR / layer["file"]
            if not tif_path.exists():
                return jsonify({"error": "Layer data not yet available"}), 404

            try:
                from osgeo import gdal
                ds = gdal.Open(str(tif_path))
                bbox = [
                    ds.GetGeoTransform()[0],
                    ds.GetGeoTransform()[3]
                    + ds.RasterYSize * ds.GetGeoTransform()[5],
                    ds.GetGeoTransform()[0]
                    + ds.RasterXSize * ds.GetGeoTransform()[1],
                    ds.GetGeoTransform()[3],
                ]
                stats = ds.GetRasterBand(1).GetStatistics(True, True)
                ds = None
            except ImportError:
                bbox = [116.0, 4.0, 130.0, 22.0]
                stats = [0, 0, 0, 0]

            return jsonify({
                "id": layer["id"],
                "name": layer["name"],
                "description": layer["description"],
                "units": layer["units"],
                "bbox": bbox,
                "statistics": {
                    "min": stats[0],
                    "max": stats[1],
                    "mean": stats[2],
                    "stddev": stats[3],
                },
                "size_bytes": tif_path.stat().st_size,
            })

    return jsonify({"error": "Layer not found"}), 404


@app.route("/api/query", methods=["GET"])
def query_point():
    """Return power-density value at a geographic point."""
    lat = request.args.get("lat", type=float)
    lon = request.args.get("lon", type=float)

    if lat is None or lon is None:
        return jsonify({"error": "lat and lon query parameters required"}), 400

    layer_id = request.args.get("layer", "tidal_power_density")
    for layer in LAYERS:
        if layer["id"] == layer_id:
            tif_path = OUTPUT_DIR / layer["file"]
            if not tif_path.exists():
                return jsonify({"error": "Layer data not available"}), 404
            break
    else:
        return jsonify({"error": "Layer not found"}), 404

    try:
        from osgeo import gdal
        ds = gdal.Open(str(tif_path))
        geotransform = ds.GetGeoTransform()
        px = int((lon - geotransform[0]) / geotransform[1])
        py = int((lat - geotransform[3]) / geotransform[5])
        value = float(ds.GetRasterBand(1).ReadAsArray(px, py, 1, 1)[0, 0])
        ds = None
    except Exception as e:
        return jsonify({
            "lat": lat, "lon": lon,
            "value": None,
            "error": str(e),
        })

    return jsonify({
        "lat": lat,
        "lon": lon,
        "value": value if value != 0 else None,
        "units": "W/m²",
    })


@app.route("/api/download", methods=["GET"])
def download_data():
    """Download GeoTIFF or CSV export."""
    layer_id = request.args.get("layer", "tidal_power_density")
    fmt = request.args.get("format", "tif")

    for layer in LAYERS:
        if layer["id"] == layer_id:
            tif_path = OUTPUT_DIR / layer["file"]
            if not tif_path.exists():
                return jsonify({"error": "Layer data not available"}), 404

            if fmt == "tif":
                return send_file(
                    str(tif_path),
                    mimetype="image/tiff",
                    as_attachment=True,
                    download_name=layer["file"],
                )
            elif fmt == "csv":
                return jsonify({
                    "error": "CSV export not yet implemented — use GeoTIFF instead"
                }), 501
            else:
                return jsonify({"error": f"Unsupported format: {fmt}"}), 400

    return jsonify({"error": "Layer not found"}), 404


@app.route("/api/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({
        "status": "ok",
        "data_dir": str(OUTPUT_DIR),
        "files": [p.name for p in OUTPUT_DIR.glob("*.tif")],
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
