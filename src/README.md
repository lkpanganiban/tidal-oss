# src/ — Modelling & Web Visualisation

```
src/
├── model/                 # 2D shallow-water screening model
│   ├── run.py             # CLI entry point
│   ├── config.yaml        # Default simulation parameters
│   ├── solver.py          # Forward-backward Arakawa C-grid solver
│   ├── grid.py            # Structured grid definition
│   ├── forcing.py         # Tidal BC (synthetic | FES2014 | TPXO9 | GOT4.10c)
│   ├── bathymetry.py      # GEBCO loading, clipping, regridding, shapefile land mask
│   ├── output.py          # NetCDF, Cloud-Optimised GeoTIFF, GeoJSON writer
│   └── tests/             # Conservation, channel, and seiche tests
├── web/                   # Flask API + MapLibre GL JS frontend
│   ├── app.py             # Flask application (tiles, queries, downloads)
│   ├── requirements.txt   # Python dependencies
│   └── static/
│       └── index.html     # Interactive map
└── Dockerfile             # All-in-one Docker image
```

---

## Step 0 — Download external datasets

The model can run on synthetic data, but for realistic simulations you need:

| Dataset | Size | Auto-download? | Required for |
|---|---|---|---|
| GEBCO 2024 bathymetry | ~2.7 GB | No (licence) | Real bathymetry |
| OSM Philippines shoreline | ~25 MB | Yes | Land mask |
| GADM Philippines boundary | ~15 MB | Yes | Land mask |
| GOT4.10c (NASA) | ~44 MB | Yes (no registration!) | Real tidal forcing (recommended) |
| FES2014 tidal harmonics | ~2 GB | No (AVISO) | Real tidal forcing |
| TPXO9-atlas tidal harmonics | ~4.1 GB | No (TPXO) | Alternative real forcing |

### Using the downloader

```bash
python downloader.py                # guided interactive mode (y/N prompts)
python downloader.py --all          # auto-download OSM + GADM; show manual steps for the rest
python downloader.py --shoreline    # OSM + GADM only
python downloader.py --tidal        # show FES2014 + TPXO9 manual download instructions
python downloader.py --gebco        # show GEBCO manual instructions
python downloader.py --data-dir ./downloaded_data   # custom output directory
```

Automatically downloaded zips are extracted in-place. Already-present files are skipped unless `--force` is passed.

After downloading, update `src/model/config.yaml` to point at your data:

```yaml
bathymetry:
  path: data/GEBCO_2024.nc             # ← set this
  land_shapefile: data/gadm41_PHL_shp/gadm41_PHL_0.shp  # or null

tidal_forcing:
  source: got                           # synthetic | fes2014 | tpxo9 | got
  path: data/GOT4.10c/grids_oceantide_netcdf/  # dir for GOT/FES, file for TPXO

output:
  dir: output/
```

### Manual downloads

- **GEBCO 2024:** https://www.gebco.net/data_and_products/gridded_bathymetry_data/gebco_2024/
- **GOT4.10c:** https://earth.gsfc.nasa.gov/geo/data/ocean-tide-models (free, no registration)
- **FES2014:** https://www.aviso.altimetry.fr/en/data/products/auxiliary-products/global-tide-fes.html
- **TPXO9-atlas:** https://www.tpxo.net/global/tpxo9-atlas

### Extraction

Automatically downloaded zips (OSM, GADM) are extracted in-place by the downloader. For manually downloaded archives, extract them with:

```bash
# GOT4.10c tar.gz
tar xzf data/got4.10c.tar.gz -C data/

# OSM shapefile zip (if downloaded manually)
unzip data/philippines-latest-free.shp.zip -d data/philippines-latest-free.shp/

# GADM boundary zip (if downloaded manually)
unzip data/gadm41_PHL_shp.zip -d data/gadm41_PHL_shp/
```

Expected directory layout:

```
data/
├── GEBCO_2024.nc
├── fes2014/
│   ├── M2_ocean.nc
│   ├── M2_load.nc
│   ├── S2_ocean.nc
│   ├── S2_load.nc
│   ├── K1_ocean.nc
│   ├── K1_load.nc
│   ├── O1_ocean.nc
│   └── O1_load.nc
├── tpxo9/
│   └── h_tpxo9.v1.nc
├── GOT4.10c/
│   └── grids_oceantide_netcdf/
│       ├── m2.nc
│       ├── s2.nc
│       ├── k1.nc
│       ├── o1.nc
│       └── ...
├── philippines-latest-free.shp/       # extracted OSM shapefiles
└── gadm41_PHL_shp/
    └── gadm41_PHL_0.shp               # land-polygon boundary
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

pip install numpy scipy xarray pyyaml rasterio fiona affine netCDF4

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

To use real GEBCO bathymetry, set `bathymetry.path` in config.yaml to a local GEBCO NetCDF file. The model derives a land mask from the GADM Philippines shapefile (`land_shapefile` key). Set `land_shapefile: null` to use GEBCO elevation > 0 as a fallback. Without bathymetry, the model runs on a synthetic rectangular test grid.

### Option B: Docker

```bash
docker build -t tidal-model -f src/Dockerfile .

docker run --rm \
  -v "$(pwd)/output:/output" \
  --entrypoint python \
  tidal-model \
  -m model.run --output-dir /output
```

The model logs progress every hour; duration and resolution are read from `src/model/config.yaml` (15 days at 2 km by default).

### Run the test suite

```bash
docker run --rm --entrypoint python tidal-model -m pytest /app/src/model/tests/

# Or locally:
python -m pytest src/model/tests/
```

---

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
pip install flask numpy rasterio pillow

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
  docker run --rm -v "$(pwd)/output:/output" --entrypoint python tidal-model -m model.run --output-dir /output && \
  docker compose up -d
```
