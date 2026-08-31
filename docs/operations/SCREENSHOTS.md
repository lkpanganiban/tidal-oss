# End-to-end workflow: screening → TELEMAC-2D → web visualisation

This page documents the full, *actually-executed* pipeline that turns real
input data (GEBCO bathymetry, GOT4.10c tidal harmonics, a land mask) into a
hydrodynamic model run, a TELEMAC-2D refinement, and the interactive web map
served by the MSP tool.  It is the companion to
`../architecture/WORKFLOW.md` and `../engines/TELEMAC.md` and shows every stage,
the exact commands, and the screenshots captured at each step.

## Prerequisites

* Docker 24+ (the public TELEMAC image `flussplan/telemac:v8-latest`)
* Python 3.10+ with `src/requirements.txt` installed
* The input datasets configured in `src/model/config.yaml`
  (GEBCO NetCDF, `data/GOT4.10c/grids_oceantide_netcdf/`,
  `data/philippines_landmass.geojson`)
* Playwright + Chromium for the web screenshots:
  `pip install playwright && playwright install chromium`

## Stage 1 — Screening model

Run the Python shallow-water solver over the archipelago.  It writes
`results.nc`, four GeoTIFF layers, and `hotspots.geojson` (cells ≥ 200 W/m²):

```bash
python -m src.model.run
```

A full 15-day run takes ~40 minutes at 2 km resolution (it auto-computes
`dt` from the CFL condition).  On completion:

```
2026-08-27 10:10:57 [INFO]   hotspots (> 200 W/m²) = 1559 cells
Done. Output written to: output/tidal_power_density.tif
```

## Stage 2 — TELEMAC case preparation

The refinement workflow is driven by `src/model/telemac/`.  Two configs ship:

* `scripts/telemac_demo_config.yaml` — reuses the *same real data* but shortens
  the TELEMAC steering (2 days instead of 15) so the public Docker image
  finishes quickly.  Open boundaries on the box's east/west edges.
* `scripts/telemac_strait_config.yaml` — a Surigao Strait refinement (single
  hotspot around 121.5°E, 6.1°N) with `edge_types: top/bottom = liquid`,
  `propagation_axis: lat`, `phase_speed_mps: 2.0` so the tide propagates
  through the strait instead of sloshing (see `../engines/TELEMAC.md`).  The
  screenshots in this repo were captured from this run.

Prepare a case — cluster the screening hotspots and generate the mesh /
boundary / steering files:

```bash
PYTHONPATH=src python -m model.telemac \
  --config scripts/telemac_strait_config.yaml \
  prepare --cases-dir cases
```

Each region becomes a self-contained case:

```
cases/region-001/
├── mesh.slf            # triangular geometry (generated from the screening grid)
├── mesh.cli            # boundary conditions (liquid/solid points)
├── mesh.liq            # tidal elevation time series (same GOT harmonics)
├── case.cas            # TELEMAC steering file
├── mesh_manifest.json  # projection + node lon/lat for post-processing
└── manifest.json       # provenance (image, bbox, forcing, timing)
```

## Stage 3 — TELEMAC-2D run (public Docker image)

Execute the case inside the pinned public image.  The runner mounts the case
directory, sources the image's TELEMAC environment, and invokes `telemac2d.py`:

```bash
PYTHONPATH=src python -m model.telemac \
  --config scripts/telemac_strait_config.yaml \
  run --case cases/region-001
```

Key output from a successful run:

```
                      CORRECT END OF RUN
... handling result files
        moving: r2d.slf
My work is done
```

The result file `cases/region-001/r2d.slf` holds the elevation and velocity
fields at every time step (5761 steps for the 2-day demo).

> **Apple Silicon:** the image is `linux/amd64`.  Docker Desktop runs it via
> Rosetta automatically; add `--platform linux/amd64` explicitly if needed.

## Stage 4 — Post-processing

Rasterise the unstructured node fields back to the regular lon/lat grid and
write the *same* canonical outputs the screening model produces:

```bash
PYTHONPATH=src python -m model.telemac \
  --config scripts/telemac_strait_config.yaml \
  postprocess --case-dir cases/region-001 \
  --output-dir output/telemac/region-001
```

Result (identical contract to Stage 1, so the web app is engine-agnostic):

```
output/telemac/region-001/
├── results.nc                 # time series (eta/u/v/power), tagged source=telemac2d
├── tidal_power_density.tif
├── max_current_speed.tif
├── bathymetry.tif
├── distance_to_coast.tif
└── hotspots.geojson
```

## Stage 5 — Serve the refinement in the web app

Point the Flask service at the TELEMAC output folder (the app reads the power
GeoTIFF path and derives the sibling layers/timeseries from it):

```bash
GEOTIFF_PATH="$PWD/output/telemac/region-001/tidal_power_density.tif" \
  python -m src.web.app --host 127.0.0.1 --port 5055
```

> **macOS:** port 5000 is owned by ControlCenter (AirPlay) and returns HTTP
> 403.  Use a different port (5055 shown) and pass it to the screenshot driver
> with `--base`.

Verify the API serves the refinement (all endpoints read the TELEMAC outputs):

```bash
curl http://127.0.0.1:5055/api/layers                 # all 4 layers available
curl "http://127.0.0.1:5055/api/timeseries?lat=9.85&lon=125.50"   # 5761 points
curl "http://127.0.0.1:5055/api/turbine_performance?lat=9.85&lon=125.50"
curl http://127.0.0.1:5055/api/resource?min_power=0.05   # area/MW/AEP totals
```

## Stage 6 — Screenshots

With the web server running, capture every interaction state with the
Playwright driver:

```bash
python scripts/capture_screenshots.py --base http://127.0.0.1:5055 --out screenshots
```

The driver waits for the map/layers/charts to settle (no fixed sleeps where it
matters) and saves a named PNG per state at 1440×900:

| File | Shows |
|------|-------|
| `01-map-power-overview.png` | Refined power-density layer centred on the region |
| `02-map-all-layers.png` | Power + speed + depth + distance overlays |
| `03-map-satellite.png` | Esri satellite basemap |
| `04-map-dark.png` | CARTO dark basemap |
| `05-site-inspector.png` | Clicked hotspot: point stats, tidal curve, turbine performance, power curve |
| `06-hotspots-list.png` | Ranked hotspot sites panel |
| `07-export-menu.png` | GeoTIFF / CSV export menu |
| `08-polygon-assessment.png` | Drawn-polygon site assessment results |
| `09-resource-screening.png` | Filtered resource totals (area / MW / AEP) |
| `10-measure-tool.png` | Distance-measure mode |

## Reproducibility notes

* The demo config (`scripts/telemac_demo_config.yaml`) shortens only the
  TELEMAC *steering* (`duration_days: 2`, `max_regions: 1`); bathymetry,
  forcing, and mesh are the real ones.  Lower `hotspot_threshold` there if you
  want more hotspots exported from a low-power region.
* Screening and refinement outputs are gitignored (`output/`, `cases/`); the
  demo config and screenshot driver live under `scripts/`, so they are tracked.
* The Selafin reader/writer handles both the modern binary SERAFIN layout
  (produced by TELEMAC v7/v8) and legacy ASCII files, with endianness
  auto-detection.
* The `.liq` file is written **one column per liquid boundary segment** (not
  per node); each segment carries its own imposed phase lag, which is what
  makes the strait boundaries genuinely out of phase (see
  `../engines/TELEMAC.md`).  The strait meshes are land-aware: coastal edges become
  solid walls, open edges become the two liquid segments.
* `scripts/capture_screenshots.py` takes `--base <url>`; the server port must
  match (5055 here, since macOS port 5000 is blocked by ControlCenter).