"""Tests for config validation, the streaming NetCDF writer, and resume."""

from __future__ import annotations

import os
import tempfile

import numpy as np
import pytest

from model.config import load_config, validate_config
from model.grid import StructuredGrid
from model.output import (
    NetCDFStreamWriter,
    mean_power_from_netcdf,
    read_last_state,
)
from model.run import run

# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------


def _default_config() -> dict:
    return load_config()


def test_validate_default_config_ok():
    validate_config(_default_config())


def test_validate_missing_section():
    cfg = _default_config()
    del cfg["simulation"]
    with pytest.raises(ValueError, match="simulation"):
        validate_config(cfg)


def test_validate_bad_duration():
    cfg = _default_config()
    cfg["simulation"]["duration_days"] = -1.0
    with pytest.raises(ValueError, match="duration_days"):
        validate_config(cfg)


def test_validate_bad_cfl_safety():
    cfg = _default_config()
    cfg["simulation"]["cfl_safety"] = 2.0
    with pytest.raises(ValueError, match="cfl_safety"):
        validate_config(cfg)


def test_validate_unknown_tidal_source():
    cfg = _default_config()
    cfg["tidal_forcing"]["source"] = "mars_tides"
    with pytest.raises(ValueError, match="source"):
        validate_config(cfg)


def test_validate_real_source_requires_path():
    cfg = _default_config()
    cfg["tidal_forcing"]["source"] = "got"
    cfg["tidal_forcing"]["path"] = None
    with pytest.raises(ValueError, match="path"):
        validate_config(cfg)


def test_validate_no_constituents():
    cfg = _default_config()
    cfg["tidal_forcing"]["constituents"] = []
    with pytest.raises(ValueError, match="constituents"):
        validate_config(cfg)


# ---------------------------------------------------------------------------
# Streaming writer
# ---------------------------------------------------------------------------


def _tiny_grid() -> StructuredGrid:
    lon = np.linspace(120.0, 122.0, 12)
    lat = np.linspace(10.0, 12.0, 10)
    return StructuredGrid.from_bathymetry(
        lon, lat, np.full((10, 12), 40.0), min_depth=2.0
    )


def test_stream_writer_roundtrip():
    grid = _tiny_grid()
    tmpdir = tempfile.mkdtemp()
    path = os.path.join(tmpdir, "results.nc")

    with NetCDFStreamWriter(
        path, grid, rho=1026.0, cd=0.003, extra_attrs={"source": "synthetic"}
    ) as w:
        for k in range(4):
            eta = np.full(grid.shape, 0.1 * k)
            u = np.full((grid.ny, grid.nx + 1), 0.2 * k)
            v = np.full((grid.ny + 1, grid.nx), 0.3 * k)
            w.write_snapshot(float(k) * 600.0, eta, u, v, np.full(grid.shape, float(k)))

    import xarray as xr

    ds = xr.open_dataset(path, decode_times=False)
    assert ds["eta"].shape == (4, grid.ny, grid.nx)
    assert ds["u"].shape == (4, grid.ny, grid.nx + 1)
    assert ds["v"].shape == (4, grid.ny + 1, grid.nx)
    assert ds["power_density"].shape == (4, grid.ny, grid.nx)
    assert ds.attrs["rho"] == 1026.0
    assert ds.attrs["cd"] == 0.003
    assert ds.attrs["source"] == "synthetic"
    assert np.allclose(ds["eta"][-1], 0.3)
    ds.close()

    t, eta, u, v = read_last_state(path)
    assert t == 3 * 600.0
    assert np.allclose(eta, 0.3)

    mean = mean_power_from_netcdf(path)
    assert np.allclose(mean, 1.5)  # mean of [0, 1, 2, 3]


def test_stream_writer_append_mode():
    grid = _tiny_grid()
    tmpdir = tempfile.mkdtemp()
    path = os.path.join(tmpdir, "results.nc")

    with NetCDFStreamWriter(path, grid, mode="w") as w:
        w.write_snapshot(
            0.0,
            np.zeros(grid.shape),
            np.zeros((grid.ny, grid.nx + 1)),
            np.zeros((grid.ny + 1, grid.nx)),
            np.zeros(grid.shape),
        )
    with NetCDFStreamWriter(path, grid, mode="a") as w:
        w.write_snapshot(
            600.0,
            np.ones(grid.shape),
            np.ones((grid.ny, grid.nx + 1)),
            np.ones((grid.ny + 1, grid.nx)),
            np.ones(grid.shape),
        )

    import xarray as xr

    with xr.open_dataset(path, decode_times=False) as ds:
        assert ds["time"].size == 2
        assert np.allclose(ds["eta"][0], 0.0)
        assert np.allclose(ds["eta"][1], 1.0)


# ---------------------------------------------------------------------------
# End-to-end run + resume
# ---------------------------------------------------------------------------


def _minimal_config(output_dir: str, duration_days: float) -> dict:
    return {
        "domain": {
            "lon_min": 116.0,
            "lon_max": 130.0,
            "lat_min": 4.0,
            "lat_max": 22.0,
            "resolution_km": 2.0,
        },
        "bathymetry": {"path": None, "min_depth": 2.0, "max_depth": 6000.0},
        "simulation": {
            "duration_days": duration_days,
            "dt": None,
            "cfl_safety": 0.5,
            "cd": 0.0025,
            "ah": 0.0,
            "advection": False,
            "rho": 1025.0,
        },
        "tidal_forcing": {"source": "synthetic", "constituents": ["M2"]},
        "output": {
            "dir": output_dir,
            "save_interval_hours": 1.0,
            "final_geotiff": "tidal_power_density.tif",
            "hotspots_geojson": "hotspots.geojson",
            "hotspot_threshold": 200.0,
        },
        "logging": {"level": "WARNING", "progress_interval_hours": 24.0},
    }


def test_run_then_resume():
    """A short synthetic run produces outputs; resuming appends snapshots."""
    tmpdir = tempfile.mkdtemp()

    # First segment: 0.05 days (~270 steps on the synthetic 60×40 grid).
    cfg1 = _minimal_config(tmpdir, duration_days=0.05)
    tif1 = run(cfg1)
    assert os.path.isfile(tif1)

    nc_path = os.path.join(tmpdir, "results.nc")
    assert os.path.isfile(nc_path)
    assert os.path.isfile(os.path.join(tmpdir, "hotspots.geojson"))

    import xarray as xr

    with xr.open_dataset(nc_path, decode_times=False) as ds:
        nt_first = ds["time"].size
        assert nt_first >= 1

    # Resume: extend the same run to 0.1 days total.
    cfg2 = _minimal_config(tmpdir, duration_days=0.1)
    tif2 = run(cfg2, resume_from=nc_path)
    assert os.path.isfile(tif2)

    with xr.open_dataset(nc_path, decode_times=False) as ds:
        nt_second = ds["time"].size
        assert nt_second > nt_first, (
            f"resume did not append (first={nt_first}, second={nt_second})"
        )
        times = ds["time"].values
        assert np.all(np.diff(times) > 0), "time not monotonic after resume"


# ---------------------------------------------------------------------------
# Distance-to-coast (scipy EDT semantics regression test)
# ---------------------------------------------------------------------------


def test_distance_to_coast_semantics():
    """Water cells report distance to nearest land; land cells are 0."""
    from model.grid import distance_to_coast_km

    # 1-D equivalent: land strip at column 3, 2 km cells
    mask = np.ones((1, 7), dtype=bool)
    mask[0, 3] = False  # land
    dist = distance_to_coast_km(mask, dx=2000.0, dy=2000.0)
    expected = np.array([[6.0, 4.0, 2.0, 0.0, 2.0, 4.0, 6.0]])
    assert np.allclose(dist, expected), f"got {dist}"

    # All-water domain → zero distance everywhere
    all_water = np.ones((5, 5), dtype=bool)
    assert np.all(distance_to_coast_km(all_water, 2000.0, 2000.0) == 0.0)
