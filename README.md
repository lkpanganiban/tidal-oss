# Tidal Current Energy Assessment — Open-Source Workflow

Compute and visualize tidal-current energy potential for the Philippine archipelago using a fully open-source geospatial and hydrodynamic modelling stack.

- **Screening model:** 2D shallow-water finite-difference solver (Python + NumPy)
- **Next-tier engine:** [TELEMAC-2D](https://opentelemac.org/) (finite-element, for refined site assessment)
- **Bathymetry:** [GEBCO 2024](https://www.gebco.net/data_and_products/gridded_bathymetry_data/) (15 arc-second)
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

Open **http://localhost:5000** — the map displays a tidal power density overlay with click-to-query values.

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
│   │   ├── run.py                         # CLI entry point
│   │   ├── config.yaml                    # Default simulation parameters
│   │   ├── solver.py                      # Forward-backward Arakawa C-grid solver
│   │   ├── grid.py                        # StructuredGrid dataclass + builders
│   │   ├── forcing.py                     # Tidal BC (synthetic | FES2014 | TPXO9 | GOT4.10c)
│   │   ├── bathymetry.py                  # GEBCO loading, regridding, shapefile land mask
│   │   ├── output.py                      # NetCDF, COG GeoTIFF, GeoJSON writer
│   │   ├── utils.py                       # Coriolis, CFL, interpolation helpers
│   │   └── tests/
│   │       ├── __init__.py
│   │       ├── test_conservation.py        # Mass conservation & power-density tests
│   │       ├── test_tidal_channel.py       # M2-forced channel validation
│   │       └── test_standing_wave.py       # Seiche period validation
│   ├── web/                               # Web visualisation
│   │   ├── __init__.py
│   │   ├── app.py                         # Flask API (tiles, queries, downloads)
│   │   ├── requirements.txt               # Web-only dependencies
│   │   └── static/
│   │       └── index.html                 # MapLibre GL JS interactive map
│   ├── notebooks/
│   │   └── 01_hydrodynamic_model.ipynb    # Educational walkthrough
│   ├── requirements.txt                   # Consolidated Python dependencies
│   ├── Dockerfile                         # All-in-one image
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
├── docker-compose.yml                     # Service orchestration
├── .gitignore
├── docs/
│   ├── plan.md                            # Detailed implementation plan
│   ├── model.md                           # Physics & methodology reference
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

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | MapLibre GL JS interactive map |
| `/api/metadata` | GET | GeoTIFF bounds, CRS, stats, max zoom |
| `/api/query?lat=&lon=` | GET | Power-density value at a point (W/m²) |
| `/api/tiles/{z}/{x}/{y}.png` | GET | Colormapped 256×256 PNG tiles |
| `/api/download/tidal_power_density.tif` | GET | Download the full GeoTIFF |

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
| `simulation` | `rho` | 1025.0 | Seawater density (kg/m³) |
| `tidal_forcing` | `source` | `got` | `synthetic`, `got`, `fes2014`, or `tpxo9` |
| `tidal_forcing` | `path` | GOT netCDF dir | Path to constituent files |
| `tidal_forcing` | `constituents` | [M2, S2, K1, O1] | Which harmonics to include |
| `output` | `dir` | `output/` | Output directory |
| `output` | `save_interval_hours` | 1 | Snapshot save interval |
| `output` | `hotspot_threshold` | 200.0 | Hotspot minimum (W/m²) |
| `logging` | `level` | `INFO` | Log level |
| `logging` | `progress_interval_hours` | 1.0 | Progress log frequency |

Override via CLI: `python -m src.model.run --duration-days 30 --resolution-km 1.0 --output-dir my_output`

## Validation

- [Seiche period](src/model/tests/test_standing_wave.py) — validated against Merian's formula for closed basins
- [Tidal channel](src/model/tests/test_tidal_channel.py) — validated against analytic M2-forced channel solution
- [Mass conservation](src/model/tests/test_conservation.py) — drift remains below 0.01% in production runs
- Compare water levels against [NAMRIA](https://www.namria.gov.ph/) tide gauges or [IOC sea-level stations](https://www.ioc-sealevelmonitoring.org/)
- Cross-check hotspots against known tidal-energy sites (San Bernardino Strait, Surigao Strait)

## Test Suite

```bash
# Docker
docker run --rm --entrypoint python tidal-model -m pytest /app/src/model/tests/

# Local
python -m pytest src/model/tests/
```

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Docker build fails at `pip install rasterio` | The image needs `libgdal-dev`; ensure it installs before pip |
| `max|η|=0.00 m \| max|U|=0.00 m/s` in logs | Config points to a bathymetry file but no open-boundary cells exist — ensure `land_shapefile` is set or use `null` for the elevation-based fallback |
| Model produces NaN | CFL safety factor too high — lower `cfl_safety` to 0.25 or explicitly set `dt` in config |
| GeoTIFF not found (404 on tiles) | Run the model first to generate `output/tidal_power_density.tif` |
| Flask cannot find results | Verify `./output` is volume-mounted at `/output` in the container |
| Model runs slowly | Reduce `duration_days` or increase `resolution_km` for testing |
| `netCDF4` / `fiona` import error | Run `pip install -r src/requirements.txt` |
| Tidal boundary all NaN | GOT source data has NaN over land — update to latest `forcing.py` which fills NaN before interpolation |

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
