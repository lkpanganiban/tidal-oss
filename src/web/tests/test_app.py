"""Tests for the Flask web service — MSP API (layers, tiles, query,
timeseries, hotspots, area stats, resource totals, downloads)."""

from __future__ import annotations

import os

import numpy as np

import web.app as web_app


def _hot_cell_lonlat() -> tuple[float, float]:
    """Read back the location of the peak power cell."""
    import rasterio
    from rasterio.warp import transform as reproject

    with rasterio.open(web_app.GEOTIFF_PATH) as src:
        data = src.read(1)
        row, col = np.unravel_index(np.nanargmax(data), data.shape)
        xs, ys = rasterio.transform.xy(src.transform, [row], [col])
        if src.crs is not None and src.crs.to_epsg() != 4326:
            lons, lats = reproject(src.crs, "EPSG:4326", xs, ys)
        else:
            lons, lats = xs, ys
    return float(lats[0]), float(lons[0])


# ---------------------------------------------------------------------------
# Core routes
# ---------------------------------------------------------------------------


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
    assert data["units"] == "W/m²"
    assert data["stats"]["max"] > 0


def test_metadata_missing_raster(tmp_path):
    web_app.GEOTIFF_PATH = os.path.join(tmp_path, "does_not_exist.tif")
    web_app.app.config.update(TESTING=True)
    with web_app.app.test_client() as c:
        resp = c.get("/api/metadata")
        assert resp.status_code == 200
        assert resp.get_json()["available"] is False


# ---------------------------------------------------------------------------
# Layers endpoint
# ---------------------------------------------------------------------------


def test_layers_endpoint(client):
    resp = client.get("/api/layers")
    assert resp.status_code == 200
    data = resp.get_json()
    assert set(data["layers"]) == {"power", "speed", "depth", "distance"}
    assert data["results_nc"] is True
    for name in ("power", "speed", "depth", "distance"):
        meta = data["layers"][name]
        assert meta["available"] is True
        assert meta["units"]
        assert meta["stats"]["max"] >= 0
        assert len(meta["legend"][0]) == 5


def test_layers_endpoint_missing(tmp_path):
    web_app.GEOTIFF_PATH = os.path.join(tmp_path, "nope.tif")
    web_app.app.config.update(TESTING=True)
    with web_app.app.test_client() as c:
        data = c.get("/api/layers").get_json()
        assert data["layers"]["power"]["available"] is False
        assert data["results_nc"] is False


# ---------------------------------------------------------------------------
# Layered tiles
# ---------------------------------------------------------------------------


def test_tile_valid_png(client):
    for layer in ("power", "speed", "depth", "distance"):
        resp = client.get(f"/api/tiles/{layer}/5/10/15.png")
        assert resp.status_code == 200, f"{layer} tile failed"
        assert resp.mimetype == "image/png"
        assert resp.data[:8] == b"\x89PNG\r\n\x1a\n"
        assert "max-age" in resp.headers.get("Cache-Control", "")
    # Legacy alias without layer name
    resp = client.get("/api/tiles/5/10/15.png")
    assert resp.status_code == 200
    # Repeated request hits the cache
    resp2 = client.get("/api/tiles/5/10/15.png")
    assert resp2.data == resp.data


def test_tile_out_of_range(client):
    assert client.get("/api/tiles/5/32/0.png").status_code == 404
    assert client.get("/api/tiles/5/0/32.png").status_code == 404
    assert client.get("/api/tiles/5/-1/0.png").status_code == 404
    assert client.get("/api/tiles/-1/0/0.png").status_code == 404
    assert client.get("/api/tiles/99/0/0.png").status_code == 204


def test_tile_unknown_layer(client):
    assert client.get("/api/tiles/bogus/5/10/15.png").status_code == 404


def test_tile_missing_raster(tmp_path):
    web_app.GEOTIFF_PATH = os.path.join(tmp_path, "nope.tif")
    web_app.app.config.update(TESTING=True)
    with web_app.app.test_client() as c:
        assert c.get("/api/tiles/5/10/15.png").status_code == 404


# ---------------------------------------------------------------------------
# Point queries
# ---------------------------------------------------------------------------


def test_query_hot_cell(client):
    lat, lon = _hot_cell_lonlat()
    resp = client.get(f"/api/query?lat={lat}&lon={lon}")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["layer"] == "power"
    assert data["value"] > 200  # resampling may reduce the peak; still hot


def test_query_all_layers(client):
    lat, lon = _hot_cell_lonlat()
    for layer in ("power", "speed", "depth", "distance"):
        resp = client.get(f"/api/query?lat={lat}&lon={lon}&layer={layer}")
        assert resp.status_code == 200
        assert resp.get_json()["value"] >= 0


def test_query_unknown_layer(client):
    resp = client.get("/api/query?lat=11&lon=121&layer=bogus")
    assert resp.status_code == 400


def test_query_requires_params(client):
    assert client.get("/api/query").status_code == 400
    assert client.get("/api/query?lat=abc&lon=1").status_code == 400


def test_query_outside_domain(client):
    assert client.get("/api/query?lat=0.0&lon=0.0").status_code == 404


# ---------------------------------------------------------------------------
# Time series
# ---------------------------------------------------------------------------


def test_timeseries(client):
    lat, lon = _hot_cell_lonlat()
    resp = client.get(f"/api/timeseries?lat={lat}&lon={lon}")
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data["time_hours"]) == 3
    assert len(data["eta_m"]) == 3
    assert len(data["speed_mps"]) == 3
    assert len(data["power_wm2"]) == 3
    assert data["summary"]["n_points"] == 3
    assert data["summary"]["max_speed_mps"] > 0
    assert data["summary"]["mean_power_wm2"] >= 0
    assert data["time_hours"][0] == 0.0


def test_timeseries_requires_params(client):
    assert client.get("/api/timeseries").status_code == 400


def test_timeseries_missing(tmp_path):
    web_app.GEOTIFF_PATH = os.path.join(tmp_path, "nope.tif")
    web_app.app.config.update(TESTING=True)
    with web_app.app.test_client() as c:
        assert c.get("/api/timeseries?lat=11&lon=121").status_code == 404


# ---------------------------------------------------------------------------
# Hotspots
# ---------------------------------------------------------------------------


def test_hotspots(client):
    resp = client.get("/api/hotspots")
    assert resp.status_code == 200
    fc = resp.get_json()
    assert fc["type"] == "FeatureCollection"
    assert len(fc["features"]) == 1
    assert fc["features"][0]["properties"]["power_density_Wm2"] == 500.0


def test_hotspots_filters(client):
    assert len(client.get("/api/hotspots?min=1000").get_json()["features"]) == 0
    assert len(client.get("/api/hotspots?min=300").get_json()["features"]) == 1
    assert len(client.get("/api/hotspots?limit=5").get_json()["features"]) == 1


def test_hotspots_missing(tmp_path):
    web_app.GEOTIFF_PATH = os.path.join(tmp_path, "nope.tif")
    web_app.app.config.update(TESTING=True)
    with web_app.app.test_client() as c:
        assert c.get("/api/hotspots").status_code == 404


# ---------------------------------------------------------------------------
# Area statistics (site selection)
# ---------------------------------------------------------------------------


def test_area_stats(client):
    lat, lon = _hot_cell_lonlat()
    ring = [
        [lon - 0.5, lat - 0.5],
        [lon + 0.5, lat - 0.5],
        [lon + 0.5, lat + 0.5],
        [lon - 0.5, lat + 0.5],
    ]
    resp = client.post("/api/area_stats", json={"polygon": ring, "efficiency": 0.4})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["n_cells"] >= 1
    assert data["area_km2"] > 0
    assert data["mean_power_density"] > 0
    assert data["gross_mw"] > 0
    assert data["aep_gwh_yr"] > 0
    assert data["depth_range_m"] is not None


def test_area_stats_empty_polygon(client):
    ring = [[119.0, 9.0], [119.1, 9.0], [119.1, 9.1]]  # outside the 120–122°E raster
    resp = client.post("/api/area_stats", json={"polygon": ring})
    assert resp.status_code == 200
    assert resp.get_json()["n_cells"] == 0


def test_area_stats_bad_requests(client):
    assert client.post("/api/area_stats", json={}).status_code == 400
    assert (
        client.post("/api/area_stats", json={"polygon": [[0, 0], [1, 1]]}).status_code
        == 400
    )
    assert (
        client.post(
            "/api/area_stats",
            json={"polygon": [[0, 0], [1, 0], [0, 1]], "efficiency": 2.0},
        ).status_code
        == 400
    )


# ---------------------------------------------------------------------------
# Resource totals (filters)
# ---------------------------------------------------------------------------


def test_resource_totals(client):
    resp = client.get("/api/resource?min_power=200")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["n_cells"] >= 1
    assert data["aep_gwh_yr"] > 0


def test_resource_filters(client):
    assert client.get("/api/resource?min_power=99999").get_json()["n_cells"] == 0
    # Depth layer is 40 m everywhere → depth range [39, 41] contains the hot cell
    assert (
        client.get("/api/resource?min_power=200&depth_min=0&depth_max=100").get_json()[
            "n_cells"
        ]
        >= 1
    )
    # Depth range excluding the hot cell (all water is 40 m)
    assert (
        client.get(
            "/api/resource?min_power=200&depth_min=200&depth_max=300"
        ).get_json()["n_cells"]
        == 0
    )


def test_resource_bad_params(client):
    assert client.get("/api/resource?min_power=-5").status_code == 400
    assert client.get("/api/resource?efficiency=5").status_code == 400
    assert client.get("/api/resource?depth_min=100&depth_max=10").status_code == 400


# ---------------------------------------------------------------------------
# Downloads
# ---------------------------------------------------------------------------


def test_download_layers(client):
    for name in (
        "tidal_power_density.tif",
        "bathymetry.tif",
        "max_current_speed.tif",
        "distance_to_coast.tif",
        "hotspots.geojson",
        "results.nc",
    ):
        resp = client.get(f"/api/download/{name}")
        assert resp.status_code == 200, f"download {name} failed"
        assert len(resp.data) > 0


def test_download_denied(client):
    assert client.get("/api/download/evil.txt").status_code == 404
    assert client.get("/api/download/../../etc/passwd").status_code == 404


# ---------------------------------------------------------------------------
# Colormap
# ---------------------------------------------------------------------------


def test_colormap_shape():
    data = np.ma.masked_invalid(np.array([[0.0, 1800.0, np.nan]]))
    rgba = web_app._apply_colormap(
        data, nodata=None, cmap_stops=web_app.POWER_CMAP, vmin=0.0, vmax=2000.0
    )
    assert rgba.shape == (1, 3, 4)
    assert rgba.dtype == np.uint8
    assert rgba[0, 0, 3] == 255
    assert rgba[0, 1, 3] == 255
    assert rgba[0, 2, 3] == 0
    assert rgba[0, 1, 0] > rgba[0, 0, 0]


# ---------------------------------------------------------------------------
# netCDF4 thread-safety regression (concurrent timeseries reads)
# ---------------------------------------------------------------------------


def test_concurrent_timeseries_does_not_crash(client):
    """Concurrent results.nc reads must not segfault (netCDF4 is not
    thread-safe; app.py serialises access with a lock)."""
    import threading

    results: list[Exception | None] = []

    def worker():
        try:
            web_app._timeseries(16.0, 121.0)
        except Exception as exc:  # pragma: no cover - should not happen
            results.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not results, f"concurrent timeseries failed: {results}"
