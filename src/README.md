# src/ — Modelling & Web Visualisation

```
src/
├── model/                     # 2D shallow-water screening model
│   ├── __init__.py            # Package init
│   ├── run.py                 # CLI entry point
│   ├── config.yaml            # Default simulation parameters
│   ├── solver.py              # Forward-backward Arakawa C-grid solver
│   ├── grid.py                # StructuredGrid dataclass + builders
│   ├── forcing.py             # Tidal BC (synthetic | FES2014 | TPXO9 | GOT4.10c)
│   ├── bathymetry.py          # GEBCO loading, clamping, regridding, shapefile land mask
│   ├── output.py              # NetCDF, Cloud-Optimised GeoTIFF, GeoJSON writer
│   ├── utils.py               # Coriolis, CFL, interpolation helpers
│   └── tests/                 # Conservation, channel, and seiche tests
│       ├── __init__.py
│       ├── test_conservation.py
│       ├── test_tidal_channel.py
│       └── test_standing_wave.py
├── web/                       # Flask API + MapLibre GL JS frontend
│   ├── __init__.py
│   ├── app.py                 # Flask application (tiles, queries, downloads)
│   ├── requirements.txt       # Web-only Python dependencies
│   └── static/
│       └── index.html         # Interactive map
├── notebooks/
│   └── 01_hydrodynamic_model.ipynb  # Educational walkthrough
├── requirements.txt           # Consolidated Python dependencies
└── Dockerfile                 # All-in-one Docker image
```

---

## Step 0 — Download external datasets

The model can run on synthetic data, but for realistic simulations you need:

| Dataset | Size | Auto-download? | Required for |
|---|---|---|---|
| GEBCO 2026 bathymetry (PH subset) | ~64 MB | Yes (COG range requests) | Real bathymetry |
| Philippines landmass (GeoBoundaries ADM0) | ~2.5 MB | Yes | Land mask |
| GOT4.10c (NASA GSFC) | ~44 MB | Yes (no registration!) | Real tidal forcing (recommended) |
| FES2014 tidal harmonics | ~2 GB | No (AVISO registration) | Real tidal forcing |
| TPXO9-atlas tidal harmonics | ~4.1 GB | No (TPXO registration) | Alternative real forcing |

### Using the downloader

```bash
python downloader.py                  # guided interactive mode (y/N prompts)
python downloader.py --all            # auto-download GEBCO + landmask + GOT4.10c; show manual steps for the rest
python downloader.py --gebco          # GEBCO 2026 subset only
python downloader.py --landmask       # Philippines landmass only
python downloader.py --tidal          # GOT4.10c + manual instructions for FES2014, TPXO9
python downloader.py --data-dir ./downloaded_data     # custom output directory
```

- **GEBCO** is read from a cloud-optimised GeoTIFF mirror on `data.source.coop`
  via rasterio range requests, so only the ~17 MB Philippines window is
  transferred (not the 7.4 GB global grid) and written as a GEBCO-format
  NetCDF at `data/gebco/gebco_2026_n22.0_s4.0_w112.0_e128.0.nc`.
- **Landmask** is the GeoBoundaries Philippines ADM0 GeoJSON
  (`data/philippines_landmass.geojson`).
- **GOT4.10c** archive is downloaded and auto-extracted to `data/GOT4.10c/`.

Already-present files are skipped unless `--force` is passed. The paths in
`src/model/config.yaml` already point at these locations.

### Manual downloads

- **GEBCO 2026 (official global NetCDF, 7.4 GB):** https://dap.ceda.ac.uk/bodc/gebco/global/gebco_2026/
- **GOT4.10c:** https://earth.gsfc.nasa.gov/geo/data/ocean-tide-models (free, no registration)
- **FES2014:** https://www.aviso.altimetry.fr/en/data/products/auxiliary-products/global-tide-fes.html
- **TPXO9-atlas:** https://www.tpxo.net/global/tpxo9-atlas

### Extraction

For manually downloaded archives, extract them with:

```bash
# GOT4.10c tar.gz
tar xzf data/got4.10c.tar.gz -C data/
```

Expected directory layout:

```
data/
├── gebco/
│   └── gebco_2026_n22.0_s4.0_w112.0_e128.0.nc
├── philippines_landmass.geojson
├── fes2014/                      # manual
│   ├── M2_ocean.nc
│   └── ...
├── tpxo9/                        # manual
│   └── h_tpxo9.v1.nc
└── GOT4.10c/
    └── grids_oceantide_netcdf/
        ├── m2.nc
        ├── s2.nc
        ├── k1.nc
        ├── o1.nc
        └── ...
```

---

## Step 1 — Generate output

The model produces three files from a tidal simulation:

- `output/results.nc` — full time series (NetCDF)
- `output/tidal_power_density.tif` — mean power density raster (Cloud-Optimised GeoTIFF)
- `output/hotspots.geojson` — point features above hotspot threshold

### Option A: Local Python

```bash
cd /path/to/tidal-oss

pip install -r src/requirements.txt

python -m src.model.run
```

Override defaults via CLI flags:

```bash
python -m src.model.run --duration-days 30 --resolution-km 1.0 --output-dir my_output
```

Or point to a custom config:

```bash
python -m src.model.run --config src/model/config.yaml
```

To use real GEBCO bathymetry, set `bathymetry.path` in config.yaml to a local GEBCO NetCDF file. The model derives a land mask from the Philippines landmass GeoJSON (`land_shapefile` key). Set `land_shapefile: null` to use GEBCO elevation > 0 as a fallback. Without bathymetry, the model runs on a synthetic rectangular test grid.

### Option B: Docker

```bash
docker build -t tidal-model -f src/Dockerfile .

docker run --rm \
  -v "$(pwd)/output:/output" \
  -v "$(pwd)/data:/app/data" \
  --entrypoint python \
  tidal-model \
  -m model.run --output-dir /output
```

The model logs progress every hour; duration and resolution are read from `src/model/config.yaml` (15 days at 2 km by default).

### Run the test suite

```bash
# Docker
docker run --rm --entrypoint python tidal-model -m pytest /app/src/model/tests/

# Local
python -m pytest src/model/tests/
```

---

## Step 1b — TELEMAC-2D refinement (alternative engine)

TELEMAC-2D is an *alternative* hydrodynamic engine for refining screening
hotspots at higher resolution on an unstructured mesh. It runs only inside a
public Docker image (default `flussplan/telemac:v8-latest`, pinned in
`src/model/config.yaml`). The screening model must already have produced
`output/hotspots.geojson` (run Step 1 first, or the pipeline runs it for you).

Set the engine:

```yaml
engine:
  name: telemac2d
```

Then run the full Docker-driven pipeline (screen → cluster → TELEMAC →
post-process):

```bash
scripts/telemac_pipeline.sh
```

Or step by step with Compose:

```bash
docker compose up --abort-on-container-exit tidal-screening   # 1. screening
docker compose run --rm tidal-prepare                          # 2. cluster -> cases/
docker compose run --rm -e CASE_DIR=/cases/region-001 tidal-telemac   # 3. run
docker compose run --rm tidal-postprocess                      # 4. canonical outputs
```

Or with the Python CLI (no Compose):

```bash
python -m model.telemac prepare --cases-dir cases
python -m model.telemac run --case cases/region-001            # via Docker
python -m model.telemac postprocess --case-dir cases/region-001 \
    --output-dir output/telemac/region-001
```

Refinement outputs land in `output/telemac/<region>/` and are served by the web
app exactly like the screening outputs. See `docs/engines/TELEMAC.md` and the linked
pages for mesh, boundary, and post-processing details.

## Step 2 — Run the web service

The web service requires `output/tidal_power_density.tif` to exist.

### Option A: docker compose

```bash
docker compose up -d
```

### Option B: Docker directly

```bash
docker run -p 5000:5000 -v "$(pwd)/output:/output" tidal-model
```

### Option C: Local Python

```bash
pip install -r src/requirements.txt

GEOTIFF_PATH=output/tidal_power_density.tif \
  python -m src.web.app --host 0.0.0.0 --port 5000
```

---

## Step 3 — Verify

Open **http://localhost:5000** in a browser. The map should display the Philippines with the tidal power density overlay and a legend.

### API endpoints

| Endpoint | Description |
|---|---|
| `GET /` | MapLibre GL JS interactive map |
| `GET /api/metadata` | GeoTIFF bounds, stats, availability |
| `GET /api/query?lat=&lon=` | Power density at a point |
| `GET /api/tiles/{z}/{x}/{y}.png` | Colormapped 256×256 PNG tiles |
| `GET /api/download/tidal_power_density.tif` | Download the GeoTIFF |

```bash
curl http://localhost:5000/api/metadata | jq
curl "http://localhost:5000/api/query?lat=12.5&lon=122.5"
```

## All-in-one (Docker)

For a single command that builds the image, runs the model, and starts the web service:

```bash
docker build -t tidal-model -f src/Dockerfile . && \
  mkdir -p output && \
  docker run --rm \
    -v "$(pwd)/output:/output" \
    -v "$(pwd)/data:/app/data" \
    --entrypoint python \
    tidal-model \
    -m model.run --output-dir /output && \
  docker compose up -d
```
