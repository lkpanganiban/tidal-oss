"""Tests for the TELEMAC-2D refinement adapter (pure-Python portions).

These tests exercise the parts that do not require the TELEMAC Docker image or
the geospatial stack (rasterio/netCDF4): Selafin I/O, mesh generation,
steering-file generation, hotspot clustering, boundary-file generation, and a
guarded post-processing test when scipy/rasterio are available.
"""

from __future__ import annotations

import json
import os
import struct

import numpy as np
import pytest

from model.grid import StructuredGrid
from model.telemac import (
    cluster_hotspots,
    generate_boundaries,
    generate_mesh_from_grid,
    read_geometry,
    read_serafin,
    write_geometry,
)
from model.telemac.case import compute_times
from model.telemac.selafin import SERAFIN_MAGIC, _pack_int5, _write_record


def _synthetic_grid(nx=6, ny=5):
    grid = StructuredGrid.from_uniform(nx=nx, ny=ny, dx=2000.0, dy=2000.0, lat0=12.0)
    lon = 120.0 + np.arange(nx) * (2000.0 / 111320.0)
    lat = 10.0 + np.arange(ny) * (2000.0 / 110540.0)
    grid.lon, grid.lat = np.meshgrid(lon, lat)
    grid.h = np.full((ny, nx), 80.0)
    grid.mask = np.ones((ny, nx), dtype=bool)
    return grid


def test_selafin_geometry_roundtrip(tmp_path):
    x = np.array([0.0, 1.0, 0.0, 1.0], dtype=np.float32)
    y = np.array([0.0, 0.0, 1.0, 1.0], dtype=np.float32)
    ikle = np.array([[0, 1, 3], [0, 3, 2]], dtype=np.int64)
    path = tmp_path / "mesh.slf"
    write_geometry(path, x, y, ikle, bed_elevation=-x)
    geom = read_geometry(str(path))
    assert geom.npoin == 4
    assert geom.nelem == 2
    assert geom.ndp == 3
    assert geom.x.shape == (4,)
    assert np.allclose(geom.values, -x.astype(np.float64))
    assert int((geom.ipobo > 0).sum()) == 4


def test_selafin_result_read(tmp_path):
    x = np.array([0.0, 1.0, 0.0, 1.0], dtype=np.float32)
    y = np.array([0.0, 0.0, 1.0, 1.0], dtype=np.float32)
    ikle = np.array([[0, 1, 3], [0, 3, 2]], dtype=np.int64)
    var_names = ["ELEVATION Z", "VELOCITY U"]
    times = np.array([0.0, 10.0, 20.0])
    eta = np.array([[0.0, 1.0, 2.0, 3.0], [0.1, 1.1, 2.1, 3.1], [0.2, 1.2, 2.2, 3.2]])
    u = np.array([[1.0, 1.0, 1.0, 1.0], [2.0, 2.0, 2.0, 2.0], [3.0, 3.0, 3.0, 3.0]])
    data = {"ELEVATION Z": eta, "VELOCITY U": u}

    path = tmp_path / "r2d.slf"
    with open(path, "wb") as f:
        title = ("RESULT".ljust(72) + SERAFIN_MAGIC.decode()).encode()[:80].ljust(80, b" ")
        _write_record(f, title)
        _write_record(f, (_pack_int5(len(var_names)) + _pack_int5(0)).ljust(80, b" "))
        for name in var_names:
            rec = (name[:16].ljust(16) + "M".ljust(16)).encode()
            _write_record(f, rec)
        iparam = b"".join(_pack_int5(v) for v in [1, 0, 0, 0, 0, 0, 0, 0, 0, 0]).ljust(80, b" ")
        _write_record(f, iparam)
        _write_record(f, (_pack_int5(ikle.shape[0]) + _pack_int5(x.shape[0]) + _pack_int5(3)).ljust(80, b" "))
        _write_record(f, (ikle + 1).astype(np.int32).ravel().tobytes())
        ipobo = np.array([1, 2, 3, 4], dtype=np.int32)
        _write_record(f, ipobo.tobytes())
        _write_record(f, x.astype(np.float32).tobytes())
        _write_record(f, y.astype(np.float32).tobytes())
        for t_idx, t in enumerate(times):
            _write_record(f, struct.pack("<f", t))
            for name in var_names:
                _write_record(f, data[name][t_idx].astype(np.float32).tobytes())

    res = read_serafin(str(path))
    assert res["times"].shape == (3,)
    assert res["variables"]["ELEVATION Z"].shape == (3, 4)
    assert np.allclose(res["variables"]["ELEVATION Z"][-1], eta[-1])
    assert np.allclose(res["node_x"], x.astype(np.float64))


def test_mesh_generation_from_grid(tmp_path):
    grid = _synthetic_grid()
    bbox = {"lon_min": 119.9, "lon_max": 121.0, "lat_min": 9.9, "lat_max": 11.0}
    mesh = generate_mesh_from_grid(grid, bbox, str(tmp_path / "mesh.slf"))
    geom = read_geometry(mesh.path)
    assert geom.npoin == 6 * 5
    assert mesh.coordinates_are_meters
    assert mesh.node_lon.min() >= bbox["lon_min"] - 1e-6
    assert mesh.node_lon.max() <= bbox["lon_max"] + 1e-6


def test_steering_default_and_template(tmp_path):
    from model.telemac.steering import build_steering

    cfg = {"steering": {"time_step": 25.0, "duration_days": 10, "variables": ["ELEVATION Z"]}}
    build_steering(str(tmp_path), 25.0, 100, cfg)
    text = (tmp_path / "case.cas").read_text()
    assert "TIME STEP : 25" in text
    assert "NUMBER OF TIME STEPS : 100" in text
    assert "GEOMETRY FILE : mesh.slf" in text

    template = tmp_path / "tpl.cas"
    template.write_text("GEOMETRY FILE : {{GEOMETRY}}\nSTEPS : {{NSTEPS}}\n")
    cfg2 = {"steering": {"template": str(template)}}
    build_steering(str(tmp_path), 25.0, 100, cfg2)
    text2 = (tmp_path / "case.cas").read_text()
    assert "GEOMETRY FILE : mesh.slf" in text2
    assert "STEPS : 100" in text2


def test_hotspot_clustering(tmp_path):
    gj = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [122.0, 12.0]},
                "properties": {"power_density_Wm2": 500.0},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [122.05, 12.05]},
                "properties": {"power_density_Wm2": 480.0},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [125.0, 8.0]},
                "properties": {"power_density_Wm2": 300.0},
            },
        ],
    }
    p = tmp_path / "hotspots.geojson"
    p.write_text(json.dumps(gj))
    regions = cluster_hotspots(str(p), cluster_radius_km=15.0, max_regions=3)
    assert len(regions) == 2
    assert regions[0].max_power == 500.0
    assert regions[0].bbox["lon_max"] > 122.0


def test_boundary_files_synthetic(tmp_path):
    grid = _synthetic_grid()
    bbox = {"lon_min": 120.0, "lon_max": 120.02, "lat_min": 10.0, "lat_max": 10.02}
    mesh = generate_mesh_from_grid(grid, bbox, str(tmp_path / "mesh.slf"))
    times, _ = compute_times(1.0, 0.5)
    mesh_cfg = {
        "boundary": {
            "edge_types": {"left": "liquid", "right": "liquid", "top": "solid", "bottom": "solid"}
        }
    }
    tidal = {"source": "synthetic", "constituents": ["M2"], "amplitude": 0.5}
    bset = generate_boundaries(mesh, mesh_cfg, tidal, times, str(tmp_path))
    assert os.path.isfile(bset.cli_path)
    assert os.path.isfile(bset.liq_path)
    cli_lines = (tmp_path / "mesh.cli").read_text().strip().split("\n")
    assert len(cli_lines) == bset.n_boundary_points
    liq_first = (tmp_path / "mesh.liq").read_text().strip().split("\n")
    assert liq_first[0].strip().startswith("T")
    assert "SL(1)" in liq_first[0]
    assert len(bset.liquid_point_order) > 0


def test_postprocess_guarded(tmp_path):
    pytest.importorskip("scipy")
    pytest.importorskip("rasterio")
    pytest.importorskip("netCDF4")
    from model.telemac.case import prepare_case
    from model.telemac.postprocess import postprocess_case
    from model.telemac.steering import build_steering

    grid = _synthetic_grid()
    bbox = {"lon_min": 120.0, "lon_max": 120.02, "lat_min": 10.0, "lat_max": 10.02}
    from model.telemac.hotspots import HotspotRegion

    region = HotspotRegion(
        id="region-001",
        center_lon=120.01,
        center_lat=10.01,
        bbox=bbox,
        max_power=500.0,
        n_points=1,
    )
    config = {
        "telemac2d": {
            "mesh": {"source": "generated"},
            "steering": {"time_step": 30.0, "duration_days": 1},
            "postprocess": {"output_grid_resolution_km": 0.5},
        },
        "simulation": {"rho": 1025.0, "cd": 0.0025},
        "output": {"hotspot_threshold": 200.0},
    }
    cases_dir = tmp_path / "cases"
    pc = prepare_case(region, config, {"source": "synthetic", "constituents": ["M2"]}, str(cases_dir), grid=grid)

    build_steering(str(pc.case_dir), 30.0, 10, config["telemac2d"])
    result_path = os.path.join(pc.case_dir, "r2d.slf")
    x = np.array([0.0, 1.0, 0.0, 1.0], dtype=np.float32)
    y = np.array([0.0, 0.0, 1.0, 1.0], dtype=np.float32)
    ikle = np.array([[0, 1, 3], [0, 3, 2]], dtype=np.int64)
    with open(result_path, "wb") as f:
        title = ("R".ljust(72) + SERAFIN_MAGIC.decode()).encode()[:80].ljust(80, b" ")
        _write_record(f, title)
        _write_record(f, (_pack_int5(3) + _pack_int5(0)).ljust(80, b" "))
        for name in ["ELEVATION Z", "VELOCITY U", "VELOCITY V"]:
            _write_record(f, (name[:16].ljust(16) + "M".ljust(16)).encode())
        _write_record(f, b"".join(_pack_int5(v) for v in [1, 0, 0, 0, 0, 0, 0, 0, 0, 0]).ljust(80, b" "))
        _write_record(f, (_pack_int5(2) + _pack_int5(4) + _pack_int5(3)).ljust(80, b" "))
        _write_record(f, (ikle + 1).astype(np.int32).ravel().tobytes())
        _write_record(f, np.array([1, 2, 3, 4], dtype=np.int32).tobytes())
        _write_record(f, x.astype(np.float32).tobytes())
        _write_record(f, y.astype(np.float32).tobytes())
        for t in range(11):
            _write_record(f, struct.pack("<f", float(t) * 30.0))
            _write_record(f, np.full(4, float(t) * 0.01, dtype=np.float32).tobytes())
            _write_record(f, np.full(4, 0.5, dtype=np.float32).tobytes())
            _write_record(f, np.full(4, 0.5, dtype=np.float32).tobytes())

    summary = postprocess_case(str(pc.case_dir), config, str(tmp_path / "out"), region_id="region-001")
    assert os.path.isfile(summary["results_nc"])
    assert os.path.isfile(summary["tidal_power_density_tif"])
    assert summary["n_timesteps"] == 11
