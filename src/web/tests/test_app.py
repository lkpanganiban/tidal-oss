"""Tests for the Flask web service (tiles, query, metadata, download)."""

from __future__ import annotations

import os

import numpy as np
import pytest

import web.app as web_app
from model.grid import StructuredGrid
from model.output import write_mean_power_geotiff


@pytest.fixture()
def client(tmp_path):
    """Flask test client backed by a tiny generated GeoTIFF."""
    # Build a small degree-grid raster (12×10 cells over 2°×2°).
    nx, ny = 12, 10
    lon = np.linspace(120.0, 122.0, nx)
    lat = np.linspace(10.0, 12.0, ny)
    bathy = np.full((ny, nx), 40.0)
    grid = StructuredGrid.from_bathymetry(lon, lat, bathy, min_depth=2.0)

    power = np.zeros((ny, nx))
    power[3, 5] = 500.0  # a single hot cell
    power[7, 2] = 120.0

    tif_path = os.path.join(tmp_path, "tidal_power_density.tif")
    write_mean_power_geotiff(grid, power, tif_path)

    web_app.GEOTIFF_PATH = tif_path
    web_app.app.config.update(TESTING=True)
    with web_app.app.test_client() as c:
        yield c

    web_app.GEOTIFF_PATH = os.path.abspath(
        os.environ.get("GEOTIFF_PATH", "/output/tidal_power_density.tif")
    )


def test_index_serves_frontend(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"maplibre" in resp.data.lower()


def test_metadata_available(client):
    resp = client.get("/api/metadata")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["available"] is True
    assert data["bounds"]["west"] < data["bounds"]["east"]
    assert data["bounds"]["south"] < data["bounds"]["north"]
    assert data["crs"] == "EPSG:4326"
    assert data["units"] == "W/m2"
    assert data["stats"]["max"] > 0


def test_metadata_missing_raster(tmp_path):
    web_app.GEOTIFF_PATH = os.path.join(tmp_path, "does_not_exist.tif")
    web_app.app.config.update(TESTING=True)
    with web_app.app.test_client() as c:
        resp = c.get("/api/metadata")
        assert resp.status_code == 200
        assert resp.get_json()["available"] is False


def test_query_hot_cell(client):
    """Query the exact location of the peak cell (read back from the raster
    so the test is robust to COG reprojection to EPSG:3857)."""
    import rasterio
    from rasterio.warp import transform as reproject

    with rasterio.open(web_app.GEOTIFF_PATH) as src:
        data = src.read(1)
        row, col = np.unravel_index(np.argmax(data), data.shape)
        xs, ys = rasterio.transform.xy(src.transform, [row], [col])
        if src.crs is not None and src.crs.to_epsg() != 4326:
            lons, lats = reproject(src.crs, "EPSG:4326", xs, ys)
        else:
            lons, lats = xs, ys

    resp = client.get(f"/api/query?lat={lats[0]}&lon={lons[0]}")
    assert resp.status_code == 200
    data = resp.get_json()
    # The COG driver may resample during reprojection, so the value can be
    # lower than the original 500 W/m² — it must still be a hotspot.
    assert data["power_density_Wm2"] > 200


def test_query_requires_params(client):
    resp = client.get("/api/query")
    assert resp.status_code == 400
    resp = client.get("/api/query?lat=abc&lon=1")
    assert resp.status_code == 400


def test_query_outside_domain(client):
    resp = client.get("/api/query?lat=0.0&lon=0.0")
    assert resp.status_code == 404


def test_tile_valid_png(client):
    resp = client.get("/api/tiles/5/10/15.png")
    assert resp.status_code == 200
    assert resp.mimetype == "image/png"
    assert resp.data[:8] == b"\x89PNG\r\n\x1a\n"
    assert "max-age" in resp.headers.get("Cache-Control", "")
    # Repeated request should hit the in-process cache (same bytes)
    resp2 = client.get("/api/tiles/5/10/15.png")
    assert resp2.data == resp.data


def test_tile_out_of_range(client):
    # z=5 → valid x/y in [0, 31]
    assert client.get("/api/tiles/5/32/0.png").status_code == 404
    assert client.get("/api/tiles/5/0/32.png").status_code == 404
    assert client.get("/api/tiles/5/-1/0.png").status_code == 404
    # Negative z never matches Werkzeug's <int:> converter → router 404
    assert client.get("/api/tiles/-1/0/0.png").status_code == 404
    assert client.get("/api/tiles/99/0/0.png").status_code == 204


def test_tile_missing_raster(tmp_path):
    web_app.GEOTIFF_PATH = os.path.join(tmp_path, "nope.tif")
    web_app.app.config.update(TESTING=True)
    with web_app.app.test_client() as c:
        assert c.get("/api/tiles/5/10/15.png").status_code == 404


def test_download_geotiff(client):
    resp = client.get("/api/download/tidal_power_density.tif")
    assert resp.status_code == 200
    assert resp.mimetype == "image/tiff"
    assert len(resp.data) > 0


def test_colormap_shape():
    data = np.ma.masked_invalid(np.array([[0.0, 1800.0, np.nan]]))
    rgba = web_app._apply_colormap(data, nodata=None)
    assert rgba.shape == (1, 3, 4)
    assert rgba.dtype == np.uint8
    # Valid cells opaque; NaN cell fully transparent
    assert rgba[0, 0, 3] == 255
    assert rgba[0, 1, 3] == 255
    assert rgba[0, 2, 3] == 0
    # Red channel rises with value
    assert rgba[0, 1, 0] > rgba[0, 0, 0]
