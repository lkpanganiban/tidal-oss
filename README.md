# Tidal Current Energy Assessment — Open-Source Workflow

Compute and visualize tidal-current energy potential for the Philippine archipelago using a fully open-source geospatial and hydrodynamic modelling stack.

- **Screening model:** 2D shallow-water finite-difference solver (Python + NumPy)
- **Next-tier engine:** [TELEMAC-2D](https://opentelemac.org/) (finite-element, for refined site assessment)
- **Bathymetry:** [GEBCO](https://www.gebco.net/data_and_products/gridded_bathymetry_data/) global grid (15 arc-second), clipped to the Philippines — e.g. the `gebco_2026_n19.03_s14.0_w118.0_e124.0.nc` clip in `data/gebco_bathymetry/`
- **Tidal forcing:** GOT4.10c (NASA), FES2014 (AVISO), TPXO9 (OSU), or synthetic tide
- **Land mask:** GADM Philippines shapefile (rasterised onto model grid)
- **Web stack:** Flask + MapLibre GL JS

## Architecture

Two-phase workflow: a fast Python screening model identifies hotspots, then TELEMAC-2D refines them.

```
Phase A: Screening                                Phase B: Web Visualization
═══════════════════════                           ═══════════════════════════

 GEBCO  ──┐
 GOT4.10c ┤ ── model.run ──┬── results.nc              Flask (REST API)
          ─┘               ├── tidal_power_density.tif  │
                           └── hotspots.geojson    MapLibre GL JS
```

[Full workflow diagram](docs/workflow.drawio) | [Implementation plan](docs/plan.md) | [Physics & methodology](docs/model.md) | [Step-by-step guide](src/README.md) | [Jupyter notebook](src/notebooks/01_hydrodynamic_model.ipynb)

## Quick Start

### Prerequisites

| Tool | Minimum Version |
|------|----------------|
| Python | 3.10+ |
| Docker | 24+ |
| Docker Compose | v2+ |

### 1. Download external datasets

```bash
# Auto-download OSM shoreline, GADM boundary, and GOT4.10c tidal harmonics (~100 MB total)
python downloader.py --all

# Extract GOT4.10c after download:
tar xzf data/got4.10c.tar.gz -C data/

# GEBCO bathymetry requires manual download (licence):
#   https://www.gebco.net/data_and_products/gridded_bathymetry_data/gebco_2024/
```

See [src/README.md](src/README.md) for manual download URLs, extraction instructions, and full dataset details.

### 2. Install Python dependencies

```bash
pip install -r src/requirements.txt
pip install numba        # optional: ~5× faster solver (auto-enabled)
```

### 3. Generate output with the screening model

```bash
# Run with GOT4.10c tidal forcing and GADM land mask (configured in config.yaml)
python -m src.model.run

# Override duration or resolution via CLI:
python -m src.model.run --duration-days 30 --resolution-km 1.0 --output-dir my_output
```

The run produces in `output/`:

| File | Description |
|------|-------------|
| `results.nc` | Full time series (NetCDF) |
| `tidal_power_density.tif` | Mean power density raster (Cloud-Optimised GeoTIFF) |
| `hotspots.geojson` | Point features above hotspot threshold |

### 4. Start the web service

```bash
docker compose up -d
```

Open **http://localhost:5000** — the map opens centred on **Baguio City** and
displays the full MSP workspace: switchable basemaps (OpenStreetMap / Esri
satellite / dark), multi-layer overlays (power, current speed, bathymetry,
distance to coast), click-to-query with tidal curves, **turbine performance
modelling for 10 real tidal in-stream turbines**, polygon site assessment,
hotspot ranking, and resource screening filters.

### 5. Verify

```bash
curl http://localhost:5000/api/metadata | jq
curl "http://localhost:5000/api/query?lat=12.5&lon=122.5"
```

## Project Structure

```
.
├── src/
│   ├── model/                             # Screening model (Python)
│   │   ├── __init__.py                    # Package init
│   │   ├── run.py                         # CLI entry point (python -m src.model.run)
│   │   ├── config.py                      # Config loading & validation
│   │   ├── config.yaml                    # Default simulation parameters
│   │   ├── solver.py                      # Forward-backward Arakawa C-grid solver
│   │   ├── kernels.py                     # Numba-JIT fused step kernel (optional, 5× speedup)
│   │   ├── grid.py                        # StructuredGrid dataclass + builders
│   │   ├── forcing.py                     # Tidal BC (synthetic | FES2014 | TPXO9 | GOT4.10c)
│   │   ├── bathymetry.py                  # GEBCO loading, regridding, shapefile land mask
│   │   ├── output.py                      # Streaming NetCDF, COG GeoTIFF, GeoJSON writer
│   │   ├── utils.py                       # Coriolis, CFL, interpolation helpers
│   │   └── tests/
│   │       ├── __init__.py
│   │       ├── test_conservation.py        # Mass conservation & power-density tests
│   │       ├── test_tidal_channel.py       # M2-forced channel validation
│   │       ├── test_standing_wave.py       # Seiche period validation
│   │       ├── test_end_to_end.py          # Full-pipeline integration tests
│   │       └── test_config_and_streaming.py # Config validation, streaming NetCDF, resume
│   ├── web/                               # Web visualisation
│   │   ├── __init__.py
│   │   ├── app.py                         # Flask API (tiles, queries, downloads)
│   │   ├── requirements.txt               # Web-only dependencies
│   │   ├── static/
│   │   │   └── index.html                 # MapLibre GL JS interactive map
│   │   └── tests/
│   │       └── test_app.py                # Flask API tests (tiles, query, metadata)
│   ├── notebooks/
│   │   └── 01_hydrodynamic_model.ipynb    # Educational walkthrough
│   ├── requirements.txt                   # Consolidated local-dev dependencies
│   ├── requirements-model.txt             # Model runtime dependencies
│   ├── requirements-dev.txt               # Dev/test tooling (pytest) for the image
│   ├── requirements-lock.txt              # Pinned lockfile (Docker builds)
│   ├── Dockerfile                         # All-in-one image (gunicorn, locked deps)
│   └── README.md                          # Step-by-step guide
├── data/
│   ├── .gitkeep                           # Directory tracked; contents ignored
│   ├── got4.10c.tar.gz                    # GOT4.10c archive (auto-downloaded)
│   ├── GOT4.10c/                          # Extracted tidal harmonics
│   ├── philippines-latest-free.shp/       # OSM shoreline shapefiles (auto-downloaded)
│   ├── gadm41_PHL_shp/                    # Land boundary shapefile (auto-downloaded)
│   └── gebco_bathymetry/                  # GEBCO NetCDF (manual download)
├── output/
│   └── .gitkeep                           # Directory tracked; contents ignored
├── downloader.py                          # Dataset download helper
├── generate_test_data.py                  # Synthetic data generator for the web service
├── docker-compose.yml                     # Service orchestration
├── pyproject.toml                         # Packaging, pytest, ruff, mypy, black config
├── LICENSE                                # MIT licence
├── .gitignore
├── .github/workflows/ci.yml               # Lint + type-check + test CI
├── docs/
│   ├── AGENTS.md                          # Agent/contributor context
│   ├── plan.md                            # Implementation plan
│   ├── model.md                           # Physics & methodology reference
│   ├── EXPLAINER.ipynb                    # 2-hour runnable workshop notebook
│   └── workflow.drawio                    # Visual workflow diagram
└── README.md
```

## Jupyter Notebook

`src/notebooks/01_hydrodynamic_model.ipynb` walks through the model from first principles — no physics background required. Covers:

- What tides are and why they matter
- How a computer represents the ocean (the Arakawa C-grid)
- The governing equations explained with analogies
- Bathymetry, land masking, and tidal boundary conditions
- Time-stepping, stability, and the CFL condition
- Running the model and visualising results

```bash
jupyter notebook src/notebooks/
```

## API Endpoints

The web service is a **marine spatial planning (MSP) tool** for tidal
current energy: multi-layer visualisation, site inspection with tidal
curves, polygon-based site assessment, and filtered resource screening.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | MapLibre GL JS interactive map |
| `/api/layers` | GET | Metadata for all layers (bounds, stats, units, legend) |
| `/api/tiles/{layer}/{z}/{x}/{y}.png` | GET | Colormapped 256×256 PNG tiles (`power` \| `speed` \| `depth` \| `distance`) |
| `/api/tiles/{z}/{x}/{y}.png` | GET | Alias for the power layer |
| `/api/query?lat=&lon=&layer=` | GET | Value at a point for any layer |
| `/api/timeseries?lat=&lon=` | GET | Tidal elevation / current-speed time series from `results.nc` |
| `/api/turbines` | GET | The sample set of the world's top-10 tidal in-stream turbines (specs + power curves) |
| `/api/turbine_performance?lat=&lon=` | GET | Simulated energy / capacity factor / AEP for every turbine at a site |
| `/api/hotspots?min=&limit=` | GET | Ranked hotspot sites (GeoJSON) |
| `/api/area_stats` | POST | `{"polygon": [[lon,lat],…], "efficiency": 0.4}` → resource stats within a polygon |
| `/api/resource?min_power=&depth_min=&depth_max=&efficiency=` | GET | Filtered-domain totals (area, MW, AEP GWh/yr) |
| `/api/download/{file}` | GET | Download GeoTIFFs, `hotspots.geojson`, or `results.nc` |

## Model outputs

`python -m src.model.run` now produces a full MSP layer set in `output/`:

| File | Layer | Units |
|------|-------|-------|
| `tidal_power_density.tif` | Mean power density | W/m² |
| `max_current_speed.tif` | Max depth-averaged current speed | m/s |
| `bathymetry.tif` | Bathymetric depth | m |
| `distance_to_coast.tif` | Distance to nearest coast | km |
| `results.nc` | Streaming time series (η, u, v, power) | — |
| `hotspots.geojson` | Cells above the hotspot threshold | — |

Run `python generate_test_data.py` to generate the same layer set from
synthetic data for a data-free demo.

## Model Configuration

Key parameters in `src/model/config.yaml`:

| Section | Parameter | Default | Description |
|---------|-----------|---------|-------------|
| `domain` | `lon_min`, `lon_max`, `lat_min`, `lat_max` | 116–130°E, 4–22°N | Philippine bounding box |
| `domain` | `resolution_km` | 2.0 | Grid cell size |
| `bathymetry` | `source` | `gebco` | Data source |
| `bathymetry` | `path` | GEBCO NetCDF | Path to bathymetry file |
| `bathymetry` | `min_depth` / `max_depth` | 2.0 / 6000.0 m | Depth clipping |
| `bathymetry` | `land_shapefile` | GADM .shp | Coastline polygon (`null` for elev > 0 fallback) |
| `simulation` | `start_time` | `2024-01-01T00:00:00` | Simulation start |
| `simulation` | `duration_days` | 15 | One spring-neap cycle |
| `simulation` | `dt` | `null` | Time step (`null` = auto CFL) |
| `simulation` | `cfl_safety` | 0.5 | CFL safety factor (lower = more stable) |
| `simulation` | `cd` | 0.0025 | Bottom drag coefficient |
| `simulation` | `ah` | 0.0 | Horizontal eddy viscosity (0 = off) |
| `simulation` | `advection` | `false` | Non-linear advection terms |
| `simulation` | `use_numba` | `null` | `null` = auto-JIT when numba installed (~5× faster); `true`/`false` to force |
| `simulation` | `rho` | 1025.0 | Seawater density (kg/m³) |
| `tidal_forcing` | `source` | `got` | `synthetic`, `got`, `fes2014`, or `tpxo9` |
| `tidal_forcing` | `path` | GOT netCDF dir | Path to constituent files |
| `tidal_forcing` | `constituents` | [M2, S2, K1, O1] | Which harmonics to include |
| `output` | `dir` | `output/` | Output directory |
| `output` | `save_interval_hours` | 1 | Snapshot save interval |
| `output` | `results_nc` | `results.nc` | Streaming NetCDF filename |
| `output` | `hotspot_threshold` | 200.0 | Hotspot minimum (W/m²) |
| `logging` | `level` | `INFO` | Log level |
| `logging` | `progress_interval_hours` | 1.0 | Progress log frequency |

CLI overrides:

```bash
python -m src.model.run --duration-days 30 --resolution-km 1.0 --output-dir my_output
python -m src.model.run --tidal-source synthetic          # force synthetic tide
python -m src.model.run --resume output/results.nc        # continue from last snapshot
```

If `bathymetry.path` is unset or the file is missing, the model logs a
warning and runs on a synthetic test grid — no data download needed for a
first smoke run.

## Validation

- [Seiche period](src/model/tests/test_standing_wave.py) — validated against Merian's formula for closed basins
- [Tidal channel](src/model/tests/test_tidal_channel.py) — validated against analytic M2-forced channel solution
- [Mass conservation](src/model/tests/test_conservation.py) — drift remains below 0.01% in production runs
- [Numba parity](src/model/tests/test_end_to_end.py) — the JIT kernel is bit-for-bit identical to the NumPy path
- Compare water levels against [NAMRIA](https://www.namria.gov.ph/) tide gauges or [IOC sea-level stations](https://www.ioc-sealevelmonitoring.org/)
- Cross-check hotspots against known tidal-energy sites (San Bernardino Strait, Surigao Strait)

## Test Suite

```bash
# Docker (the image ships pytest + the test suite)
docker run --rm --entrypoint python tidal-model -m pytest /app/src/model/tests/

# Local (model + web tests, config in pyproject.toml)
python -m pytest

# Lint / format / types
ruff check src downloader.py generate_test_data.py
ruff format --check src downloader.py generate_test_data.py
mypy src/model src/web
```

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Docker build fails at `pip install rasterio` | The image needs `libgdal-dev`; ensure it installs before pip |
| Dev server drops requests / timeseries 500 under load | `netCDF4` is not thread-safe — the app serialises reads with a lock; use `docker compose up` (gunicorn) for production |
| `max|η|=0.00 m \| max|U|=0.00 m/s` in logs | Config points to a bathymetry file but no open-boundary cells exist — ensure `land_shapefile` is set or use `null` for the elevation-based fallback |
| Model produces NaN | CFL safety factor too high — lower `cfl_safety` to 0.25 or explicitly set `dt` in config |
| `bathymetry.path` not found warning | Expected on a fresh clone — the model falls back to a synthetic grid; download GEBCO for production runs |
| GeoTIFF not found (404 on tiles) | Run the model first to generate `output/tidal_power_density.tif` |
| Flask cannot find results | Verify `./output` is volume-mounted at `/output` in the container |
| Model runs slowly | Install numba (`pip install numba`) — auto-enabled, ~5× faster; or reduce `duration_days` / increase `resolution_km` |
| `netCDF4` / `fiona` import error | Run `pip install -r src/requirements.txt` |
| Tidal boundary all NaN | GOT source data has NaN over land — `forcing.py` fills NaN before interpolation (already fixed) |

## Future Extensions

- TELEMAC-2D refinement of screening hotspots (unstructured mesh, higher resolution)
- TELEMAC-3D for vertical velocity profiling
- Wave-current coupling with TOMAWAC
- Real-time tidal forecasting via live boundary-condition feeds
- Economic site-screening module (depth filter, distance-to-grid)

## License

This project is released under the [MIT License](LICENSE).

## Contributing

1. Fork the repository.
2. Create a feature branch.
3. Submit a pull request with a clear description of changes.

For major changes, open an issue first to discuss what you would like to change.
