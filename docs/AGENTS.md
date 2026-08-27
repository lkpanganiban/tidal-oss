# AGENTS.md — Agent Context for the Tidal-OSS Project

This file provides the canonical context for an LLM / coding agent working on
this repository.  Read it fully before making any changes.

## 1. Activate the conda environment

**Every shell command must be prefixed with the conda activation for the
project.**  The project uses a dedicated conda environment called `tidaloss`:

```bash
source /home/bluey/miniconda3/etc/profile.d/conda.sh && conda activate tidaloss
```

If you need to run a single command inside the environment use:

```bash
source /home/bluey/miniconda3/etc/profile.d/conda.sh && conda activate tidaloss && <your command>
```

For Python scripts, the interpreter lives at:

```
/home/bluey/miniconda3/envs/tidaloss/bin/python
```

The system `python3` (base conda, Python 3.13) does **not** have all the
required packages — **always use the `tidaloss` environment**.

### Verified packages in the tidaloss environment

| Package    | Version  |
|------------|----------|
| Python     | 3.14.4   |
| numpy      | 2.4.6    |
| scipy      | 1.17.1   |
| xarray     | 2026.4.0 |
| matplotlib | 3.10.9   |
| rasterio   | 1.5.0    |
| fiona      | 1.10.1   |
| netCDF4    | 1.7.4    |
| numba      | 0.66     |
| flask      | — (web)  |
| pillow     | — (web)  |
| pytest     | 9.x      |
| ruff       | 0.16+    |
| mypy       | 2.x      |

pytest, ruff, and mypy are installed in the environment (see § 6 for usage).

## 2. Project overview

This is a **two-phase tidal-current energy assessment workflow** for the
Philippine archipelago:

- **Phase A (screening):** A 2D shallow-water finite-difference solver in
  Python + NumPy on a structured Arakawa C-grid.  This is the code in
  `src/model/`.
- **Phase B (web):** A Flask + MapLibre GL JS **marine spatial planning (MSP)**
  tool: multi-layer overlays (power density, max current speed, bathymetry,
  distance to coast), click-to-query with tidal curves (Chart.js), polygon
  site assessment (`/api/area_stats`), ranked hotspots, filtered resource
  screening (`/api/resource`), and **turbine performance modelling** for the
  top-10 real tidal in-stream turbines (`/api/turbines`,
  `/api/turbine_performance` — energy, capacity factor, AEP per turbine).
  Map opens centred on Baguio City; basemaps OSM / Esri satellite / dark.

The key insight: a fast, coarse Python model finds **hotspots** (straits with
mean tidal power density ≥ 200 W/m²), then TELEMAC‑2D refines them.

**Primary output:** `tidal_power_density.tif` — a GeoTIFF of time-mean power
density $P = \frac12 \rho |U|^3$ in W/m².

## 3. Repository layout

```
.
├── README.md                    # quick start, config table, troubleshooting
├── docker-compose.yml           # Flask + MapLibre web service
├── downloader.py                # fetch GOT4.10c, OSM, GADM datasets
├── generate_test_data.py        # synthetic data generator
├── docs/
│   ├── AGENTS.md                # ← this file
│   ├── EXPLAINER.ipynb          # 2-hour workshop notebook (runnable)
│   ├── MODEL.md                 # full physics & methodology reference
│   └── workflow.drawio          # visual pipeline diagram
├── src/
│   ├── requirements.txt         # Python dependencies (all components)
│   ├── README.md                # step-by-step guide
│   ├── Dockerfile               # all-in-one Docker image
│   ├── model/                   # screening model (Phase A)
│   │   ├── __init__.py
│   │   ├── run.py               # CLI entry point (python -m src.model.run)
│   │   ├── config.py            # config loading & validation
│   │   ├── config.yaml          # default simulation parameters
│   │   ├── grid.py              # StructuredGrid dataclass + builders
│   │   ├── solver.py            # ShallowWaterSolver (forward-backward C-grid)
│   │   ├── kernels.py           # numba-JIT fused step kernel (optional, ~5× faster)
│   │   ├── forcing.py           # tidal boundary generators (GOT/FES/TPXO)
│   │   ├── bathymetry.py        # GEBCO loading, regridding, land mask
│   │   ├── output.py            # streaming NetCDF, COG GeoTIFF, GeoJSON writer
│   │   ├── utils.py             # Coriolis, CFL, interpolation helpers
│   │   └── tests/
│   │       ├── __init__.py
│   │       ├── test_conservation.py    # mass conservation & power non-neg
│   │       ├── test_tidal_channel.py   # M2-forced channel (flow + phase)
│   │       ├── test_standing_wave.py   # seiche period (Merian's formula)
│   │       ├── test_end_to_end.py      # full-pipeline integration tests
│   │       └── test_config_and_streaming.py  # config validation, streaming, resume
│   ├── web/                     # web visualisation (Phase B)
│   │   ├── __init__.py
│   │   ├── app.py               # Flask MSP API (layers, tiles, timeseries, area stats, resource)
│   │   ├── requirements.txt     # web-only dependencies
│   │   ├── static/index.html    # MapLibre GL JS interactive map
│   │   └── tests/test_app.py    # Flask API tests
│   └── notebooks/
│       └── 01_hydrodynamic_model.ipynb  # first-principles walkthrough
├── pyproject.toml               # packaging + pytest/ruff/mypy/black config
├── LICENSE                      # MIT licence
├── .github/workflows/ci.yml     # lint + type-check + test CI
├── data/                        # external datasets (gitignored except .gitkeep)
│   ├── GOT4.10c/                # extracted per-constituent NetCDFs
│   ├── gebco_bathymetry/        # GEBCO_2024.nc (manual download)
│   ├── gadm41_PHL_shp/          # GADM country boundary
│   └── philippines-latest-free.shp/  # OSM coastline
└── output/                      # model output (gitignored except .gitkeep)
    ├── results.nc
    ├── tidal_power_density.tif
    └── hotspots.geojson
```

### 3b. TELEMAC-2D refinement backend (`src/model/telemac/`)

An *alternative* engine. The Python solver stays the default (`engine.name:
python` in `src/model/config.yaml`); set `telemac2d` to refine screening
hotspots on an unstructured mesh. Key modules:

- `selafin.py` — pure-Python Selafin (SERAFIN) mesh/result read+write.
- `mesh.py` — generated (clip screening grid + triangulate) or supplied `.slf` meshes; lon/lat ↔ local-metre projection.
- `boundaries.py` — `.cli` / `.liq` generation from the same harmonics as the screening model.
- `steering.py` — `.cas` generation (template or defaults).
- `case.py` — assembles a self-contained case directory + manifest.
- `runner.py` — invokes `telemac2d.py` inside the **public** Docker image (`telemac2d.image`, never compiled in-repo).
- `postprocess.py` — converts `r2d.slf` into the canonical `results.nc` / GeoTIFF / GeoJSON outputs.
- `cli.py` — `python -m model.telemac {prepare,run,postprocess,pipeline}`.

TELEMAC runs only via Docker; pin the image tag/digest. Docs: `docs/TELEMAC.md`,
`docs/WORKFLOW.md`, `docs/CASE_AUTHORING.md`, `docs/POSTPROCESSING.md`,
`docs/TROUBLESHOOTING.md`.

## 4. How to run the code

### 4.1 Quick test (no data needed)

```bash
source /home/bluey/miniconda3/etc/profile.d/conda.sh && conda activate tidaloss
cd /home/bluey/dev/work/tidal-oss
python -c "
from model.grid import StructuredGrid
from model.solver import ShallowWaterSolver
from model.forcing import make_synthetic_tidal_boundary
# ... (see EXPLAINER.ipynb for full examples)
"
```

(`pip install -e .` or `PYTHONPATH=src` makes the `model` / `web` packages
importable; pytest handles this automatically.)

### 4.2 Production run (with data)

```bash
python downloader.py --all          # fetch OSM, GADM, GOT4.10c
# manually place GEBCO_2024.nc into data/gebco_bathymetry/
python -m src.model.run            # uses src/model/config.yaml
docker compose up -d               # web map at http://localhost:5000
```

### 4.3 Run the EXPLAINER workshop notebook

```bash
source /home/bluey/miniconda3/etc/profile.d/conda.sh && conda activate tidaloss
cd /home/bluey/dev/work/tidal-oss
jupyter notebook docs/EXPLAINER.ipynb
```

### 4.4 Run the test suite

```bash
source /home/bluey/miniconda3/etc/profile.d/conda.sh && conda activate tidaloss
cd /home/bluey/dev/work/tidal-oss
python -m pytest          # model + web tests (config in pyproject.toml)
```

### 4.5 Lint, format, and type-check

```bash
ruff check src downloader.py generate_test_data.py
ruff format --check src downloader.py generate_test_data.py
mypy src/model src/web
```

These three commands are also enforced in CI (`.github/workflows/ci.yml`).

## 5. Key model architecture

### 5.1 Data flow

```
GEBCO NetCDF ──→ load_gebco() ──→ regrid_bathymetry() ──→ elevation_to_depth() ──┐
                                                                                 │
GADM .shp ─────→ build_land_mask() ──────────────────────────────────────────────┤
                                                                                 ├──→ StructuredGrid
GOT/FES/TPXO ──→ read_*_constituents() ──→ build_tidal_boundary() ──→ solver ───┘
NetCDF
```

### 5.2 Core classes

- **`StructuredGrid`** (`grid.py`) — dataclass holding the Arakawa C-grid:
  η at cell centres `(ny,nx)`, u at x-faces `(ny,nx+1)`, v at y-faces
  `(ny+1,nx)`.  Depth `h` positive down.  Two builders:
  `from_uniform()` (idealised) and `from_bathymetry()` (real domains).

- **`ShallowWaterSolver`** (`solver.py`) — forward-backward time stepper on
  the C-grid.  Semi-implicit bottom friction, optional Coriolis, advection,
  and horizontal viscosity (`ah`).  Key methods:
  `step(dt)`, `run(dt, duration, callback)`, `compute_power_density()`.

- **`TidalBoundary`** (`forcing.py`) — wraps harmonic constituents and
  evaluates $\eta(t) = \sum A_k \cos(\omega_k t + \phi_k)$ at boundary cells.
  Readers for GOT4.10c (`read_got_constituents`), FES2014, TPXO9.
  `make_synthetic_tidal_boundary()` for testing.

### 5.3 Important API conventions (footguns to avoid)

- **`StructuredGrid` has NO `f_u` / `f_v` attributes.**  Setting
  `grid.f[:] = 0.0` zeros the Coriolis; the solver derives `f_u`/`f_v`
  internally.  **Never write `grid.f_u[:] = 0` or `grid.f_v[:] = 0`.**

- **`StructuredGrid` has NO `eta` attribute.**  `eta` lives on the solver.
  When writing boundary-condition callables, create a zero array with
  `np.zeros((grid.ny, grid.nx))`, **not** `np.zeros_like(grid.eta)`.

- **`from_uniform()` produces metre-based lon/lat arrays** (not degrees).
  The GeoTIFF writer (`write_mean_power_geotiff`) needs a degree-based grid.
  For output demos, build the grid via `from_bathymetry()` with degree lon/lat.

- **Both open boundaries with identical prescribed η produce zero lateral
  flow.**  In a symmetric channel setup, drive only one boundary or provide
  a phase difference.

- **The `_laplacian` method** (horizontal viscosity, `ah > 0`) was previously
  broken (`slice + int` TypeError).  It was fixed on 2024‑01‑08 and now
  correctly computes the 5‑point stencil.  The default `ah = 0` never uses it.

## 6. Testing

pytest is installed and configured in `pyproject.toml` (`testpaths` covers
`src/model/tests/` and `src/web/tests/`; `pythonpath = ["src"]` means no
`PYTHONPATH` juggling is needed).  Run everything with:

```bash
python -m pytest
```

The model test modules still import pytest conditionally so they can also be
run standalone without a test runner (legacy behaviour, kept for debugging):

### Unit tests (7 tests, `test_conservation.py`, `test_tidal_channel.py`, `test_standing_wave.py`)

| Test | What it checks | Pass criterion |
|------|----------------|----------------|
| `test_mass_conservation_closed_basin` | Volume drift in a closed basin | < 1 % over ≈ 30 min |
| `test_mass_conservation_with_friction` | Friction doesn't leak mass | < 1 % over 1 h |
| `test_power_density_nonnegative` | $P \ge 0$ everywhere and $P > 0$ somewhere | — |
| `test_tidal_channel_develops_flow` | M2-forced channel at left boundary produces flow | $|u| > 0.005$ m/s at midpoint |
| `test_tidal_channel_phase` | Velocity–elevation phase is physical | phase ∈ $(-\pi/2, \pi)$ rad |
| `test_standing_wave_period` | Seiche period matches Merian's formula $T = 2L/\sqrt{gh}$ | < 10 % error |
| `test_standing_wave_no_coriolis_damping` | Seiche doesn't decay in a frictionless basin | < 30 % amplitude drop |

### End-to-end / integration tests (12 tests, `test_end_to_end.py`)

| Test | What it checks |
|------|----------------|
| `test_bathymetry_pipeline_end_to_end` | Full chain: synthetic GEBCO NetCDF → `load_gebco` → `regrid` → `elevation_to_depth` → `StructuredGrid.from_bathymetry` |
| `test_forcing_pipeline_end_to_end` | Constituent → `build_tidal_boundary` → single-time + multi-time evaluation; `make_synthetic_tidal_boundary` convenience path |
| `test_full_simulation_pipeline` | Degree-grid domain → synthetic M2+S2 → solver run → snapshots → power density → sanity checks |
| `test_output_netcdf_roundtrip` | `create_results_dataset` → `write_netcdf` → read back → verify variables, attributes, dimensions |
| `test_output_geotiff_valid` | `write_mean_power_geotiff` → verify CRS, band data, dtype, description with rasterio |
| `test_output_geojson_hotspots` | `write_hotspots_geojson` → verify FeatureCollection, geometry type, properties, threshold enforcement |
| `test_cfl_auto_computation_sensible` | `cfl_timestep` produces physically correct ordering (deeper → smaller dt; finer → smaller dt) |
| `test_power_density_formula_consistency` | `solver.compute_power_density()` matches independent `utils.power_density()` call |
| `test_open_boundary_detection` | `from_bathymetry` correctly marks wet perimeter cells and excludes interior/dry cells |
| `test_spring_neap_modulation_visible` | M2+S2 boundary produces measurable amplitude modulation over 30 days via sliding window |
| `test_solver_restart_consistency` | `run()` and manual `step()` loop produce identical final state (checkpoint compatibility) |
| `test_config_file_valid` | `config.yaml` exists, is valid YAML, and contains all expected sections with sensible values |

**How to run them all quickly** (see § 4.4 for the one-liner).

## 7. Key configuration (`src/model/config.yaml`)

| Section       | Parameter            | Default            | Notes                                |
|---------------|----------------------|--------------------|--------------------------------------|
| `domain`      | `lon_min` … `lat_max`| 116–130°E, 4–22°N  | Philippine bounding box              |
| `domain`      | `resolution_km`      | 2.0                | Finer → slower (~ Δx⁻³ cost scaling) |
| `bathymetry`  | `path`               | GEBCO NetCDF        | Set `null` for synthetic grid        |
| `bathymetry`  | `land_shapefile`     | GADM .shp           | Set `null` for elev > 0 fallback     |
| `simulation`  | `duration_days`      | 15                 | One spring–neap cycle minimum        |
| `simulation`  | `dt`                 | `null`             | Auto-compute from CFL                |
| `simulation`  | `cfl_safety`         | 0.5                | Lower to 0.25 to avoid NaN           |
| `simulation`  | `cd`                 | 0.0025             | Bottom drag coefficient              |
| `simulation`  | `ah`                 | 0.0                | Horizontal eddy viscosity            |
| `simulation`  | `advection`          | `false`            | Non-linear advection terms           |
| `simulation`  | `use_numba`          | `null`             | Auto-JIT when numba installed; force `true`/`false` |
| `tidal_forcing`| `source`            | `got`              | One of: `synthetic`, `got`, `fes2014`, `tpxo9` |
| `tidal_forcing`| `constituents`      | [M2, S2, K1, O1]   | Four-constituent minimum             |
| `output`      | `results_nc`         | `results.nc`       | Streaming NetCDF filename            |
| `output`      | `hotspot_threshold`  | 200.0              | Minimum mean power density for hotspot export (W/m²) |

## 8. Troubleshooting cheat-sheet

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `max|η|=0.00 m` in logs | No open-boundary cells are wet | Check land_shapefile or min_depth |
| Model produces NaN | CFL safety too high | Set `cfl_safety: 0.25` or set `dt` explicitly |
| `bathymetry.path not found` warning | Fresh clone with no GEBCO yet | Expected — falls back to synthetic grid; download GEBCO for production |
| Config ValueError at startup | Misconfigured config.yaml | `validate_config` message names the offending section/key |
| `grid.f_u` / `grid.f_v` AttributeError | You wrote `grid.f_u[:] = 0` | See § 5.3 — write `grid.f[:] = 0` only |
| `grid.eta` AttributeError | You wrote `np.zeros_like(grid.eta)` | See § 5.3 — use `np.zeros((g.ny, g.nx))` |
| GeoTIFF not found (404 on tiles) | Model hasn't run yet | Run `python -m src.model.run` first |
| Flask can't find results | Output not mounted in container | Check `docker-compose.yml` volume mount |
| Test import fails (`no module pytest`) | Wrong Python environment | Activate `tidaloss` conda env (§ 1) or run `pip install -e .[dev]` |
| `netCDF4` / `fiona` import error | Wrong Python environment | Activate `tidaloss` conda env (§ 1) |
| `_laplacian` TypeError | Outdated `solver.py` (< 2024‑01‑08) | Pull latest — the `slice + int` bug is fixed |

## 9. When editing code in this repo

1. **Activate the `tidaloss` environment first** (§ 1).
2. Run the test suite after every change that touches `solver.py`, `grid.py`,
   `forcing.py`, `utils.py`, or `kernels.py` (§ 4.4).
3. Run `ruff check` + `ruff format --check` + `mypy src/model src/web` after
   any edit (these gates run in CI, § 4.5).
3. Do **not** add back the patterns listed in § 5.3.
4. The `docs/EXPLAINER.ipynb` notebook must remain runnable top-to-bottom.
   If you change a model API, update the notebook to match.
5. The `_laplacian` fix in `solver.py` (5‑point stencil on interior cells)
   must not be regressed — it enables `ah > 0`.

## 10. Related documentation

| File | Content |
|------|---------|
| `README.md` | Quick start, configuration table, API endpoints, troubleshooting |
| `docs/MODEL.md` | Full physics derivation, term-by-term explanation, validation, references |
| `docs/EXPLAINER.ipynb` | 2‑hour runnable workshop (beginner-friendly, all cells pass) |
| `src/README.md` | Step-by-step setup guide, dataset URLs, file listing |
| `src/notebooks/01_hydrodynamic_model.ipynb` | First-principles educational walkthrough |
| `src/model/config.yaml` | Default parameters for the screening model |
| `src/requirements.txt` | Python dependencies |
