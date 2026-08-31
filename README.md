# Tidal Current Energy — Web Visualisation

Marine spatial planning (MSP) web app for Philippine tidal-current energy. Serves pre-computed model outputs (GeoTIFFs + NetCDF) via a Flask + MapLibre GL JS interface.

Outputs in `output/` (final processing stack):
- `tidal_power_density.tif` — mean power density [W/m²]
- `max_current_speed.tif` — max depth-averaged speed [m/s]
- `bathymetry.tif` — bathymetric depth [m]
- `distance_to_coast.tif` — distance to coast [km]
- `results.nc` — time series (η, u, v, power) [NetCDF]
- `hotspots.geojson` — ranked hotspot sites

## Quick Start

```bash
docker compose up -d --build
# open http://localhost:8001
```

Port `8001` is mapped to the container's `5000`. The map opens centred on the model domain with switchable basemaps and multi-layer overlays (power, current speed, bathymetry, distance to coast).

## API

| Endpoint | Description |
|----------|-------------|
| `/` | MapLibre GL JS interactive map |
| `/api/layers` | Metadata for all layers (bounds, stats, legend) |
| `/api/tiles/{layer}/{z}/{x}/{y}.png` | Colormapped tiles (`power` \| `speed` \| `depth` \| `distance`) |
| `/api/query?lat=&lon=&layer=` | Value at a point |
| `/api/timeseries?lat=&lon=` | Tidal curve from `results.nc` |
| `/api/turbines` | Top-10 tidal turbine specs |
| `/api/turbine_performance?lat=&lon=` | Turbine performance at a site |
| `/api/hotspots?min=&limit=` | Ranked hotspots (GeoJSON) |
| `/api/area_stats` | POST polygon → resource stats |
| `/api/resource` | Filtered-domain totals |
| `/api/download/{file}` | Download GeoTIFF / GeoJSON / NetCDF |

## Project Structure

```
.
├── src/web/
│   ├── app.py              # Flask API (tiles, queries, downloads)
│   ├── turbines.py         # Turbine dataset & performance model
│   └── static/index.html   # MapLibre GL JS frontend
├── src/Dockerfile          # Web image (python:3.12-slim + GDAL)
├── src/web/requirements.txt
├── src/requirements-lock.txt
├── docker-compose.yml      # tidal-web service (port 8001:5000)
├── output/                 # Final outputs (6 files, volume-mounted)
└── pyproject.toml
```

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r src/requirements-lock.txt
OUTPUT_DIR=output python -m web.app --port 5000  # from src/
# or
PYTHONPATH=src python -m flask --app web.app run --port 5000
```

## License

MIT — see `LICENSE`.
