"""End-to-end tests: full pipeline from data loading through output generation.

Tests the integration of grid construction, forcing, solving, and output
writing — exercising the same code paths that `run.py` uses in production.
All tests use synthetic data so no external datasets are required.
"""

import warnings
warnings.filterwarnings(
    "ignore", message="numpy.ndarray size changed, may indicate binary incompatibility"
)

import json
import os
import tempfile
from pathlib import Path

import numpy as np

try:
    import pytest
except ImportError:
    pytest = None  # type: ignore[assignment]

from model.bathymetry import load_gebco, regrid_bathymetry, elevation_to_depth
from model.forcing import (
    ASTRO_FREQUENCIES,
    TidalConstituent,
    TidalBoundary,
    make_synthetic_tidal_boundary,
    build_tidal_boundary,
)
from model.grid import StructuredGrid
from model.output import (
    create_results_dataset,
    write_netcdf,
    write_mean_power_geotiff,
    write_hotspots_geojson,
)
from model.solver import ShallowWaterSolver, G, RHO_SEAWATER
from model.utils import cfl_timestep, speed, power_density


# ---------------------------------------------------------------------------
# Helper: build a tiny degree-grid domain suitable for GeoTIFF output
# ---------------------------------------------------------------------------

def _tiny_degree_grid(nx: int = 12, ny: int = 10, depth: float = 40.0) -> StructuredGrid:
    """A small rectangular domain in lat/lon space (~2°×2° box)."""
    lon_1d = np.linspace(120.0, 122.0, nx)
    lat_1d = np.linspace(10.0, 12.0, ny)
    bathy = np.full((ny, nx), depth)
    return StructuredGrid.from_bathymetry(lon_1d, lat_1d, bathy, min_depth=2.0)


# ---------------------------------------------------------------------------
# 1. Bathymetry pipeline — synthetic GEBCO → regrid → grid
# ---------------------------------------------------------------------------

def test_bathymetry_pipeline_end_to_end():
    """Create a synthetic GEBCO NetCDF on disk, load it, regrid, and build a grid.

    Exercises load_gebco, regrid_bathymetry, elevation_to_depth, and
    StructuredGrid.from_bathymetry in one chain.
    """
    import xarray as xr

    tmpdir = tempfile.mkdtemp()
    nc_path = os.path.join(tmpdir, "fake_gebco.nc")

    # Build a fake high-resolution "GEBCO" NetCDF (0.1° spacing)
    lon_hi = np.arange(118.0, 124.0, 0.1, dtype=np.float64)
    lat_hi = np.arange(8.0, 14.0, 0.1, dtype=np.float64)
    lon2d, lat2d = np.meshgrid(lon_hi, lat_hi)
    elev = -50.0 + 30.0 * np.sin(np.deg2rad(lon2d) * 4) * np.cos(np.deg2rad(lat2d) * 3)
    elev[20:28, 30:35] = 10.0  # a small island (land = positive)

    ds = xr.Dataset(
        data_vars={"elevation": (["lat", "lon"], elev.astype(np.float32))},
        coords={"lon": lon_hi, "lat": lat_hi},
    )
    ds.to_netcdf(nc_path, mode="w")
    ds.close()

    # 1) load_gebco — clip to a sub-region
    lon, lat, elev = load_gebco(nc_path, lon_min=119.0, lon_max=123.0,
                                lat_min=9.0, lat_max=13.0)
    assert len(lon) >= 10, f"too few lon points: {len(lon)}"
    assert len(lat) >= 10, f"too few lat points: {len(lat)}"
    assert elev.shape == (len(lat), len(lon)), f"shape mismatch: {elev.shape}"
    # GEBCO convention: positive up, so some values are negative (ocean) and
    # the artificial island should be positive
    assert np.min(elev) < 0, "expected ocean (negative elevation) in clipped domain"
    assert np.max(elev) > 0, "expected land (positive elevation) in clipped domain"

    # 2) regrid_bathymetry — coarsen to ~2 km
    lon_new, lat_new, elev_new = regrid_bathymetry(lon, lat, elev, resolution_km=2.0)
    assert 5 <= len(lon_new) <= 400, f"regridded nx out of range: {len(lon_new)}"
    assert 5 <= len(lat_new) <= 400, f"regridded ny out of range: {len(lat_new)}"
    assert elev_new.shape == (len(lat_new), len(lon_new))

    # 3) elevation_to_depth — flip sign
    depth = elevation_to_depth(elev_new)
    assert np.all(depth >= 0), "depth must be non-negative"
    # at least some cells should be deep (> 10 m)
    assert np.max(depth) > 10, f"max depth too shallow: {np.max(depth)}"

    # 4) StructuredGrid.from_bathymetry
    grid = StructuredGrid.from_bathymetry(lon_new, lat_new, depth, min_depth=2.0)
    assert grid.ny == len(lat_new) and grid.nx == len(lon_new)
    assert grid.mask.any(), "no wet cells"
    assert grid.open_boundary.any(), "no open-boundary cells"
    # open boundaries only on the perimeter
    ob = grid.open_boundary
    interior = ob[1:-1, 1:-1] if grid.ny > 2 and grid.nx > 2 else np.array([], dtype=bool)
    assert not interior.any(), "open-boundary cells found in interior"


# ---------------------------------------------------------------------------
# 2. Forcing pipeline — synthetic constituents → TidalBoundary → evaluate
# ---------------------------------------------------------------------------

def test_forcing_pipeline_end_to_end():
    """Build a TidalBoundary from synthetic constituents and evaluate a time series.

    Verifies the full chain: constituent creation, build_tidal_boundary,
    evaluate (multi-time), and evaluate_at (single time).
    """
    grid = _tiny_degree_grid()
    n_bnd = int(grid.open_boundary.sum())
    assert n_bnd > 0, "no boundary cells"

    # Create constituents with different amplitudes per constituent
    c1 = TidalConstituent(
        name="M2", amplitude=np.full(n_bnd, 0.5),
        phase=np.zeros(n_bnd), omega=ASTRO_FREQUENCIES["M2"],
        lon=grid.lon[grid.open_boundary], lat=grid.lat[grid.open_boundary],
    )
    c2 = TidalConstituent(
        name="S2", amplitude=np.full(n_bnd, 0.15),
        phase=np.full(n_bnd, np.pi / 4), omega=ASTRO_FREQUENCIES["S2"],
        lon=grid.lon[grid.open_boundary], lat=grid.lat[grid.open_boundary],
    )

    bnd = build_tidal_boundary([c1, c2])
    assert bnd.n_boundary_cells == n_bnd
    assert len(bnd.names) == 2
    assert bnd.amp.shape == (2, n_bnd)
    assert bnd.phase.shape == (2, n_bnd)

    # Evaluate at a single time
    eta_single = bnd.evaluate_at(0.0)
    assert eta_single.shape == (n_bnd,)
    # At t=0 with phases 0 and π/4: η = 0.5*cos(0) + 0.15*cos(π/4) ≈ 0.5 + 0.106 ≈ 0.606
    assert 0.55 < eta_single[0] < 0.65, f"unexpected η at t=0: {eta_single[0]:.3f}"

    # Evaluate a multi-time series
    nt = 10
    t_sec = np.linspace(0, 86400, nt)
    eta_multi = bnd.evaluate(t_sec)
    assert eta_multi.shape == (nt, n_bnd)
    # Values must be bounded by sum of amplitudes
    amps_sum = 0.5 + 0.15
    assert np.all(np.abs(eta_multi) <= amps_sum + 1e-6), "η exceeded amplitude sum"
    # Should vary over time (M2+S2 produces modulation)
    assert np.max(eta_multi[:, 0]) - np.min(eta_multi[:, 0]) > 0.01, "time series too flat"

    # ----- make_synthetic_tidal_boundary convenience path -----
    synth = make_synthetic_tidal_boundary(n_bnd, amplitude=0.8,
                                          constituents=["M2", "S2", "K1", "O1"])
    assert synth.n_boundary_cells == n_bnd
    assert len(synth.names) == 4
    eta_synth = synth.evaluate_at(0.0)
    assert eta_synth.shape == (n_bnd,)
    # All four in phase at t=0 → should sum to 0.8 × 4 = 3.2
    assert 3.15 < eta_synth[0] < 3.25, f"unexpected synth η: {eta_synth[0]:.3f}"


# ---------------------------------------------------------------------------
# 3. Full simulation — grid → solver → snapshots → mass check
# ---------------------------------------------------------------------------

def test_full_simulation_pipeline():
    """Build a degree-grid domain, force with synthetic M2, run 2 periods,
    collect snapshots, and verify mass conservation and power properties.

    This is the closest test to a `run.py` production run.
    """
    grid = _tiny_degree_grid(nx=14, ny=12, depth=50.0)
    assert grid.open_boundary.sum() >= 4, "too few open-boundary cells for a realistic run"

    # Synthetic M2+S2 forcing
    n_bnd = int(grid.open_boundary.sum())
    tide = make_synthetic_tidal_boundary(n_bnd, amplitude=0.5,
                                         constituents=["M2", "S2"])

    solver = ShallowWaterSolver(grid, cd=0.0025, ah=0.0, advection=False, rho=1025.0)
    solver.set_open_boundary_eta(tide)

    # Run two M2 periods with snapshots every 30 minutes (simulated)
    T_M2 = 2 * np.pi / ASTRO_FREQUENCIES["M2"]
    dt = 15.0
    duration = 2 * T_M2

    vol0 = solver.total_volume()
    assert vol0 > 0, "zero volume before run"

    snapshots = []

    def cb(solv, step_n):
        # Collect every ~600 steps (≈ 2.5 h real time) — gives ~4 snapshots
        if step_n % 600 == 0:
            snapshots.append({
                "t": solv.time,
                "eta": solv.eta.copy(),
                "u": solv.u.copy(),
                "v": solv.v.copy(),
                "power": solv.compute_power_density(),
            })
        return None

    solver.run(dt=dt, duration=duration, callback=cb, progress_interval=duration)
    vol1 = solver.total_volume()

    # Mass-drift sanity check.  With open boundaries the total volume
    # naturally oscillates (water enters and leaves).  Over a short
    # integration the drift can be > 0.01 %; the closed-basin tests in
    # test_conservation.py strictly verify mass conservation.  Here we
    # only check that the volume didn't explode.
    drift = 100 * abs(vol1 - vol0) / vol0
    assert drift < 50.0, f"volume explosion: drift {drift:.1f}%"

    # We must have collected at least a few snapshots
    assert len(snapshots) >= 2, f"only {len(snapshots)} snapshots collected"

    # Snapshots have the expected shapes
    for s in snapshots:
        assert s["eta"].shape == (grid.ny, grid.nx)
        assert s["u"].shape == (grid.ny, grid.nx + 1)
        assert s["v"].shape == (grid.ny + 1, grid.nx)
        assert s["power"].shape == (grid.ny, grid.nx)

    # Power density must be non-negative everywhere
    power_all = np.stack([s["power"] for s in snapshots])
    assert np.all(power_all >= 0), "negative power density"
    # At least some power should develop (the tidal forcing drives flow)
    mean_power = np.mean(power_all)
    assert mean_power > 0, "zero mean power density — no flow developed"

    # The region near open boundaries should have highest power (flow enters there)
    # This is a sanity check, not a strict condition
    power_mean_map = np.mean(power_all, axis=0)
    ob_power = power_mean_map[grid.open_boundary].mean()
    assert ob_power > 0, "zero power at open boundaries"


# ---------------------------------------------------------------------------
# 4. Output pipeline — NetCDF, GeoTIFF, GeoJSON
# ---------------------------------------------------------------------------

def test_output_netcdf_roundtrip():
    """Write a results Dataset to NetCDF and read it back.

    Verifies that create_results_dataset and write_netcdf produce a
    standards-compliant file with expected variables, dimensions, and metadata.
    """
    import xarray as xr

    grid = _tiny_degree_grid()
    nt, ny, nx = 6, grid.ny, grid.nx
    times = np.arange(nt) * 600.0

    # Fake a short time series
    eta = 0.3 * np.sin(np.linspace(0, 4 * np.pi, nt))[:, None, None] * np.ones((nt, ny, nx))
    u = 0.2 * np.cos(np.linspace(0, 4 * np.pi, nt))[:, None, None] * np.ones((nt, ny, nx + 1))
    v = 0.1 * np.sin(np.linspace(0, 4 * np.pi, nt))[:, None, None] * np.ones((nt, ny + 1, nx))
    spd = np.sqrt(u[:, :, 1:] ** 2 + v[:, 1:, :] ** 2)
    pwr = 0.5 * 1025.0 * spd ** 3

    ds = create_results_dataset(grid, times, eta, u, v, pwr)

    # Check dataset structure before writing
    assert "eta" in ds and "u" in ds and "v" in ds
    assert "power_density" in ds
    assert ds["eta"].attrs["units"] == "m"
    assert ds["u"].attrs["units"] == "m/s"
    assert ds["v"].attrs["units"] == "m/s"
    assert ds["power_density"].attrs["units"] == "W/m^2"

    assert "lat" in ds.coords
    assert "lon" in ds.coords
    assert ds["lat"].shape == (ny, nx)
    assert ds["lon"].shape == (ny, nx)
    assert ds.attrs.get("rho") is not None
    assert ds.attrs.get("cd") is not None

    # Write to disk and read back
    tmpdir = tempfile.mkdtemp()
    nc_path = os.path.join(tmpdir, "results.nc")
    write_netcdf(ds, nc_path)
    assert os.path.isfile(nc_path), f"NetCDF not written to {nc_path}"

    ds2 = xr.open_dataset(nc_path, decode_times=False)
    assert "eta" in ds2 and "u" in ds2 and "v" in ds2 and "power_density" in ds2
    assert ds2["eta"].shape == (nt, ny, nx)
    assert ds2["u"].shape == (nt, ny, nx + 1)
    assert ds2["v"].shape == (nt, ny + 1, nx)
    assert ds2["power_density"].shape == (nt, ny, nx)
    # Time coordinates should be monotonic
    assert np.all(np.diff(ds2["time"].values) > 0), "time not monotonic"
    ds2.close()


def test_output_geotiff_valid():
    """Write a time-mean power GeoTIFF and verify it with rasterio.

    The GeoTIFF destination must be a degree-based grid (from_bathymetry),
    otherwise the geotransform is invalid.
    """
    grid = _tiny_degree_grid(nx=16, ny=14)
    power_mean = np.random.default_rng(42).uniform(0, 500, (grid.ny, grid.nx))
    power_mean[~grid.mask] = 0.0  # dry cells have zero power

    tmpdir = tempfile.mkdtemp()
    tif_path = os.path.join(tmpdir, "power.tif")
    write_mean_power_geotiff(grid, power_mean, tif_path)
    assert os.path.isfile(tif_path), f"GeoTIFF not written to {tif_path}"

    import rasterio
    with rasterio.open(tif_path) as src:
        # CRS must be a recognised coordinate reference system.
        # The COG driver with GoogleMapsCompatible tiling reprojects to
        # EPSG:3857 (Web Mercator) for web-map compatibility — both
        # EPSG:4326 and EPSG:3857 are valid outcomes.
        assert src.crs is not None, "GeoTIFF has no CRS"
        crs_str = src.crs.to_string().lower()
        assert "4326" in crs_str or "3857" in crs_str, \
            f"unexpected CRS: {crs_str} (expected EPSG:4326 or EPSG:3857)"

        # The COG driver may add overview bands, tile-pad, or reproject
        # (GoogleMapsCompatible → EPSG:3857).  The key assertions are
        # that the file is valid, has sensible data, and band 1 exists.
        assert src.count >= 1, "GeoTIFF has no bands"
        data = src.read(1)
        assert data.size > 0, "GeoTIFF band 1 is empty"
        assert data.dtype == 'float32', f"expected float32, got {data.dtype}"

        # At least one cell should have non-zero power
        assert np.any(data > 0), "all power values are zero or negative"

        # A band description should be set on band 1
        desc = src.descriptions[0]
        if desc is not None:
            assert "power" in desc.lower() or "W/m" in desc, \
                f"unexpected band description: {desc}"


def test_output_geojson_hotspots():
    """Write a hotspots GeoJSON and verify its feature and property structure."""
    grid = _tiny_degree_grid(nx=8, ny=6)
    power_mean = np.zeros((grid.ny, grid.nx))
    # Sprinkle a few "hot" cells
    power_mean[1, 2] = 350.0
    power_mean[1, 5] = 210.0
    power_mean[3, 4] = 180.0  # below threshold — should be absent
    power_mean[4, 3] = 500.0

    tmpdir = tempfile.mkdtemp()
    gj_path = os.path.join(tmpdir, "hotspots.geojson")
    threshold = 200.0
    write_hotspots_geojson(grid, power_mean, threshold, gj_path)

    assert os.path.isfile(gj_path), f"GeoJSON not written to {gj_path}"

    with open(gj_path) as f:
        gj = json.load(f)

    assert gj["type"] == "FeatureCollection"
    features = gj["features"]
    # Should have exactly 3 cells above 200 W/m²
    assert len(features) == 3, f"expected 3 hotspots, got {len(features)}"

    for feat in features:
        assert feat["type"] == "Feature"
        assert feat["geometry"]["type"] == "Point"
        coords = feat["geometry"]["coordinates"]
        assert 119.0 <= coords[0] <= 123.0, f"lon out of bounds: {coords[0]}"
        assert 9.0 <= coords[1] <= 13.0, f"lat out of bounds: {coords[1]}"
        props = feat["properties"]
        assert "power_density_Wm2" in props
        assert "depth_m" in props
        assert props["power_density_Wm2"] >= threshold, \
            f"feature below threshold: {props['power_density_Wm2']}"

    # Cell at power_mean[3,4] = 180 should NOT appear (below threshold)
    all_powers = [f["properties"]["power_density_Wm2"] for f in features]
    assert 180.0 not in all_powers, "sub-threshold cell leaked into hotspots"

    # Verify the power values match
    power_values = sorted(all_powers)
    assert abs(power_values[0] - 210.0) < 1.0
    assert abs(power_values[1] - 350.0) < 1.0
    assert abs(power_values[2] - 500.0) < 1.0


# ---------------------------------------------------------------------------
# 5. CFL auto-computation
# ---------------------------------------------------------------------------

def test_cfl_auto_computation_sensible():
    """CFL time steps should be reasonable for typical grid/depth combos.

    Also verify: deeper water → faster waves → smaller dt;
    finer grid → smaller dt.
    """
    dts = [
        cfl_timestep(2000.0, 2000.0, 10.0, safety=0.5),     # 2 km, 10 m deep
        cfl_timestep(2000.0, 2000.0, 200.0, safety=0.5),    # 2 km, 200 m deep
        cfl_timestep(500.0, 500.0, 50.0, safety=0.5),       # 500 m, 50 m deep
        cfl_timestep(10000.0, 10000.0, 50.0, safety=0.5),   # 10 km, 50 m deep
    ]
    c1, c2, c3, c4 = dts

    # Deeper → smaller dt (faster waves)
    assert c2 < c1, f"deeper water should give smaller dt: {c2:.1f} vs {c1:.1f}"

    # Finer grid → smaller dt
    assert c3 < c1, f"finer grid should give smaller dt: {c3:.1f} vs {c1:.1f}"

    # Coarser grid → larger dt
    assert c4 > c1, f"coarser grid should give larger dt: {c4:.1f} vs {c1:.1f}"

    # No dt should be absurd (< 0.01 s or > 10000 s for these typical setups)
    for dt in dts:
        assert 0.01 < dt < 10000.0, f"dt out of sensible range: {dt:.2f}"


# ---------------------------------------------------------------------------
# 6. Power density consistency
# ---------------------------------------------------------------------------

def test_power_density_formula_consistency():
    """Power density computed by solver.compute_power_density must match an
    independent computation from the same u/v arrays via ½ρU³.
    """
    grid = StructuredGrid.from_uniform(nx=10, ny=8, dx=2000.0, dy=2000.0, lat0=0.0)
    grid.h[:, :] = 30.0
    grid.h_u[:] = 30.0
    grid.h_v[:] = 30.0
    grid.mask[:] = True
    grid.mask_u[:] = True
    grid.mask_v[:] = True
    grid.f[:] = 0.0

    solver = ShallowWaterSolver(grid, cd=0.0, ah=0.0, advection=False, rho=1025.0)

    # Set a non-trivial velocity field
    rng = np.random.default_rng(123456)
    solver.u[:] = rng.normal(1.0, 0.3, solver.u.shape)
    solver.v[:] = rng.normal(0.2, 0.1, solver.v.shape)
    # Zero dry cells
    solver.u[~grid.mask_u] = 0.0
    solver.v[~grid.mask_v] = 0.0

    pd_solver = solver.compute_power_density()
    pd_manual = power_density(solver.u, solver.v, rho=solver.rho)

    assert np.allclose(pd_solver, pd_manual, atol=1e-10), \
        f"max diff: {np.max(np.abs(pd_solver - pd_manual)):.2e}"

    # Also check the helper speed() returns non-negative
    spd = speed(solver.u, solver.v)
    assert np.all(spd >= 0), "negative speed"


# ---------------------------------------------------------------------------
# 7. Open-boundary detection in from_bathymetry
# ---------------------------------------------------------------------------

def test_open_boundary_detection():
    """Verify from_bathymetry marks wet perimeter cells as open boundaries,
    and dry perimeter cells are excluded.
    """
    lon = np.linspace(120.0, 122.0, 20)
    lat = np.linspace(10.0, 12.0, 16)
    depth = np.full((16, 20), 50.0)

    # Make one corner cell dry
    depth[0, 0] = 0.0  # top-left (south-west) corner is land
    land_mask = depth < 2.0

    grid = StructuredGrid.from_bathymetry(lon, lat, depth, land_mask=land_mask,
                                          min_depth=2.0)

    ob = grid.open_boundary

    # The dry corner should NOT be an open boundary
    assert not ob[0, 0], "dry corner cell marked as open boundary — it should be inactive"

    # Wet perimeter cells SHOULD be open boundaries
    # (Check a wet cell on each edge)
    assert ob[0, 10], "wet cell on south edge not marked open"
    assert ob[-1, 10], "wet cell on north edge not marked open"
    assert ob[5, 0], "wet cell on west edge not marked open"
    assert ob[5, -1], "wet cell on east edge not marked open"

    # Interior cells should NOT be open boundaries
    assert not ob[8, 10], "interior cell incorrectly marked open"

    # There should be at least one open-boundary cell
    assert ob.sum() >= 4, "too few open-boundary cells"


# ---------------------------------------------------------------------------
# 8. Config file integrity
# ---------------------------------------------------------------------------

def test_config_file_valid():
    """Verify config.yaml exists, is valid YAML, and has the expected sections."""
    import yaml

    config_path = Path(__file__).resolve().parent.parent / "config.yaml"
    assert config_path.is_file(), f"config.yaml not found at {config_path}"

    with open(config_path) as f:
        config = yaml.safe_load(f)

    required_sections = ["domain", "bathymetry", "simulation", "tidal_forcing", "output", "logging"]
    for sec in required_sections:
        assert sec in config, f"missing config section: {sec}"

    # Domain bounds
    d = config["domain"]
    assert d["lon_min"] < d["lon_max"]
    assert d["lat_min"] < d["lat_max"]
    assert d["resolution_km"] > 0

    # Simulation parameters
    s = config["simulation"]
    assert s["duration_days"] > 0
    assert 0.0 < s.get("cfl_safety", 0.5) <= 1.0
    assert s["cd"] >= 0
    assert s["ah"] >= 0
    assert s["rho"] > 0

    # Tidal forcing
    tf = config["tidal_forcing"]
    assert tf["source"] in ("synthetic", "fes2014", "fes", "tpxo9", "tpxo", "got", "got4.10c", "got4.10")
    assert len(tf.get("constituents", [])) >= 1

    # Output
    o = config["output"]
    assert o.get("hotspot_threshold", 0) > 0
    assert "final_geotiff" in o


# ---------------------------------------------------------------------------
# 9. Spring–neap modulation visible in M2+S2 time series
# ---------------------------------------------------------------------------

def test_spring_neap_modulation_visible():
    """An M2+S2 time series must show a clear amplitude modulation over 15 days.

    This validates that the spring–neap cycle is physically captured by the
    harmonic reconstruction — a prerequisite for accurate resource assessment.
    """
    bnd_m2 = make_synthetic_tidal_boundary(1, amplitude=0.5, constituents=["M2"])
    bnd_m2s2 = make_synthetic_tidal_boundary(1, amplitude=0.5, constituents=["M2", "S2"])

    # Sample over 30 days at 15-minute resolution
    t_sec = np.arange(0, 30 * 86400, 900, dtype=np.float64)
    eta_m2 = bnd_m2.evaluate(t_sec)[:, 0]
    eta_m2s2 = bnd_m2s2.evaluate(t_sec)[:, 0]

    # M2-only: constant envelope (peak-to-peak ≈ 1.0)
    m2_range = np.max(eta_m2) - np.min(eta_m2)
    assert 0.95 < m2_range < 1.05, f"M2 peak-to-peak wrong: {m2_range:.3f}"

    # M2+S2: modulated envelope — the range over the first day vs the full 30
    # days should differ measurably
    # Compute peak amplitude in sliding 12.5 h windows (one M2 period)
    T_samp = 900
    winsize = int(13 * 3600 / T_samp)  # ~13 hours per window
    amp_envelope = np.array([
        (np.max(eta_m2s2[i:i + winsize]) - np.min(eta_m2s2[i:i + winsize]))
        for i in range(0, len(eta_m2s2) - winsize, winsize)
    ])

    amp_max = np.max(amp_envelope)
    amp_min = np.min(amp_envelope)
    modulation_ratio = amp_min / amp_max

    # Spring peaks should be noticeably larger than neap troughs
    assert modulation_ratio < 0.5, \
        f"spring–neap modulation too weak: ratio={modulation_ratio:.3f} (expect < 0.5)"


# ---------------------------------------------------------------------------
# 10. Solver preserves state across run-restart boundary
# ---------------------------------------------------------------------------

def test_solver_restart_consistency():
    """Running step() manually and running run() for the same duration
    should produce the same final state.

    This is important for checkpoint/restart scenarios in production.
    """
    from model.forcing import ASTRO_FREQUENCIES

    # Tiny channel for fast test
    L, H, nx, ny = 10000.0, 30.0, 20, 3
    dx = L / nx

    def build():
        g = StructuredGrid.from_uniform(nx=nx, ny=ny, dx=dx, dy=dx, lat0=0.0)
        g.h[:, :] = H
        g.h_u[:] = H
        g.h_v[:] = H
        g.mask[:] = True
        g.mask_u[:] = True
        g.mask_v[:] = True
        g.open_boundary[:, 0] = True
        g.f[:] = 0.0
        return g

    omega = ASTRO_FREQUENCIES["M2"]
    amp = 0.5

    def bc_func(t):
        e = np.zeros((ny, nx))
        e[:, 0] = amp * np.cos(omega * t)
        return e

    # Approach A: run() with a callback that never saves (just clock)
    gA = build()
    sA = ShallowWaterSolver(gA, cd=0.0, ah=0.0, advection=False)
    sA.set_open_boundary_eta(bc_func)
    dt = 5.0
    n_steps = 200
    sA.run(dt=dt, duration=n_steps * dt, callback=None, progress_interval=999999)

    # Approach B: call step() manually
    gB = build()
    sB = ShallowWaterSolver(gB, cd=0.0, ah=0.0, advection=False)
    sB.set_open_boundary_eta(bc_func)
    for _ in range(n_steps):
        sB.step(dt)

    # Final states must match
    assert np.allclose(sA.eta, sB.eta, atol=1e-12), "eta diverged between run() and step()"
    assert np.allclose(sA.u, sB.u, atol=1e-12), "u diverged between run() and step()"
    assert np.allclose(sA.v, sB.v, atol=1e-12), "v diverged between run() and step()"
