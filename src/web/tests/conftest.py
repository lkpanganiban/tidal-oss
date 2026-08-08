"""Shared test fixtures for the web API test suite."""

from __future__ import annotations

import os

import numpy as np
import pytest

import web.app as web_app
from model.grid import StructuredGrid
from model.output import (
    NetCDFStreamWriter,
    write_hotspots_geojson,
    write_mean_power_geotiff,
    write_raster_geotiff,
)


@pytest.fixture()
def client(tmp_path):
    """Flask test client backed by a tiny multi-layer dataset."""
    # Small degree-grid raster (12×10 cells over 2°×2°), one land cell.
    nx, ny = 12, 10
    lon = np.linspace(120.0, 122.0, nx)
    lat = np.linspace(10.0, 12.0, ny)
    bathy = np.full((ny, nx), 40.0)
    bathy[0, 0] = 0.0  # one land cell (top-left)
    grid = StructuredGrid.from_bathymetry(lon, lat, bathy, min_depth=2.0)

    power = np.zeros((ny, nx))
    power[3, 5] = 500.0  # a single hot cell
    power[7, 2] = 120.0
    power[~grid.mask] = np.nan  # land → NaN

    write_mean_power_geotiff(
        grid, power, os.path.join(tmp_path, "tidal_power_density.tif")
    )
    speed = np.where(
        np.isfinite(power), (2.0 * np.nan_to_num(power) / 1025.0) ** (1.0 / 3.0), np.nan
    )
    write_raster_geotiff(
        grid, speed, os.path.join(tmp_path, "max_current_speed.tif"), "max speed"
    )
    depth = np.where(grid.mask, grid.h, np.nan)
    write_raster_geotiff(
        grid, depth, os.path.join(tmp_path, "bathymetry.tif"), "bathymetric depth"
    )
    dist = np.zeros((ny, nx))
    dist[~grid.mask] = np.nan
    dist[grid.mask] = 5.0
    write_raster_geotiff(
        grid, dist, os.path.join(tmp_path, "distance_to_coast.tif"), "distance to coast"
    )

    # Small time series for /api/timeseries
    with NetCDFStreamWriter(os.path.join(tmp_path, "results.nc"), grid) as w:
        for k in range(3):
            eta = np.full(grid.shape, 0.1 * k)
            u = np.full((grid.ny, grid.nx + 1), 0.5 * (k + 1))
            v = np.full((grid.ny + 1, grid.nx), 0.2 * (k + 1))
            w.write_snapshot(
                float(k) * 3600.0, eta, u, v, np.full(grid.shape, 100.0 * k)
            )

    write_hotspots_geojson(
        grid, np.nan_to_num(power), 200.0, os.path.join(tmp_path, "hotspots.geojson")
    )

    web_app.GEOTIFF_PATH = os.path.join(tmp_path, "tidal_power_density.tif")
    web_app.app.config.update(TESTING=True)
    with web_app.app.test_client() as c:
        yield c

    web_app.GEOTIFF_PATH = os.path.abspath(
        os.environ.get("GEOTIFF_PATH", "output/tidal_power_density.tif")
    )
