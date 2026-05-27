# Step-by-Step Run Guide

This directory contains all source code, Docker configurations, and scripts for the Philippine tidal-current energy assessment.

Everything runs in Docker — no local Python/Fortran setup required beyond Docker.

---

## Table of Contents

1. [Directory Overview](#directory-overview)
2. [Step 1: Prerequisites](#step-1-prerequisites)
3. [Step 2: Download Input Data](#step-2-download-input-data)
4. [Step 3: Generate the Mesh](#step-3-generate-the-mesh)
5. [Step 4: Interpolate Bathymetry](#step-4-interpolate-bathymetry)
6. [Step 5: Prepare Tidal Boundary Conditions](#step-5-prepare-tidal-boundary-conditions)
7. [Step 6: Run the Simulation](#step-6-run-the-simulation)
8. [Step 7: Post-Process to GeoTIFF](#step-7-post-process-to-geotiff)
9. [Step 8: Start the Web Visualization Stack](#step-8-start-the-web-visualization-stack)
10. [Quick Reference: Makefile Targets](#quick-reference-makefile-targets)
11. [Troubleshooting](#troubleshooting)

---

## Directory Overview

```
src/
├── docker/
│   ├── Dockerfile.thetis         # Firedrake + Thetis container (~3 GB build)
│   └── Dockerfile.api            # Lightweight Flask API container
├── simulation/
│   ├── scripts/
│   │   ├── generate_mesh.py      # Gmsh mesh from shapefile
│   │   ├── mesh_interpolate.py   # Interpolate GEBCO → mesh nodes
│   │   ├── prepare_bc.py         # Tidal harmonics → tidal_forcing.py
│   │   ├── run_thetis.py         # Main simulation script
│   │   └── postprocess.py        # HDF5 results → COG GeoTIFF
│   ├── input/                    # Place input files here
│   │   ├── .gitkeep
│   │   └── tidal_forcing.py      # Template (replace with prepare_bc.py output)
│   └── output/                   # Simulation results written here
├── api/
│   ├── app.py                    # Flask REST API
│   └── requirements.txt
├── frontend/
│   ├── index.html                # MapLibre GL JS map
│   └── style.css
├── geoserver_data/
│   └── data/phil_tidal_energy/   # GeoServer reads COG from here
├── nginx.conf                    # Nginx reverse proxy
├── docker-compose.yml            # Orchestrates all services
└── Makefile                      # Convenience targets
```

---

## Step 1: Prerequisites

Install Docker, then clone and enter the `src/` directory:

```bash
git clone <repo-url> && cd $(basename $_)/src
```

Verify requirements:

```bash
docker --version         # ≥ 24
docker compose version   # v2+
```

If you want to run mesh generation locally (optional — can use Docker):

```bash
pip install gmsh meshio geopandas rioxarray xarray scipy
```

---

## Step 2: Download Input Data

### 2.1 GEBCO Bathymetry

1. Go to [download.gebco.net](https://download.gebco.net/)
2. Enter bounding box: **West: 116, East: 130, South: 4, North: 22**
3. Download as **GeoTIFF (Grid)** or **NetCDF**
4. Place in `simulation/input/` as `gebco_philippines.tif`

If you downloaded NetCDF, convert:

```bash
# Clip and convert (requires GDAL locally)
gdal_translate -projwin 116 22 130 4 \
  -of NetCDF NETCDF:GEBCO_2024.nc:elevation \
  simulation/input/gebco_philippines.nc

gdal_calc.py -A NETCDF:simulation/input/gebco_philippines.nc:elevation \
  --outfile=simulation/input/gebco_philippines.tif \
  --calc="where(A > 0, -9999, -A)" --NoDataValue=-9999 --type=Float32
```

### 2.2 Philippines Landmass Shapefile (GADM)

```bash
# Download Philippines GADM boundaries
curl -L -o simulation/input/gadm41_PHL_shp.zip \
  "https://geodata.ucdavis.edu/gadm/gadm4.1/shp/gadm41_PHL_shp.zip"
unzip -o simulation/input/gadm41_PHL_shp.zip -d simulation/input/shapefile/
```

Alternatively, download manually from [gadm.org](https://gadm.org/download_country_v3.html).

### 2.3 Tidal Constituents (Optional)

Real tidal harmonics from FES2014 or TPXO9 improve accuracy. Place them in `simulation/input/tides/`.

If you don't have these, the simulation will use the synthetic placeholder M2+S2+K1+O1 tide defined in `simulation/input/tidal_forcing.py`.

---

## Step 3: Generate the Mesh

Build the Thetis Docker image first (one-time, ~20–40 min):

```bash
make build
```

Generate the Gmsh mesh from the Philippines shapefile:

```bash
make mesh
```

This runs `generate_mesh.py` inside the Docker container which:
1. Reads the GADM shapefile (`simulation/input/shapefile/gadm41_PHL_0.shp`)
2. Simplifies the land boundary to 500 m tolerance
3. Generates an unstructured triangular mesh
4. Tags open-ocean edges (tag 1) and land edges (tag 2)
5. Writes `simulation/input/mesh_philippines.msh`

To customize mesh resolution:

```bash
docker compose run --rm thetis-shell /data/scripts/generate_mesh.py \
  --shapefile /data/input/shapefile/gadm41_PHL_0.shp \
  --output /data/input/mesh_philippines.msh \
  --lc-ocean 0.1 --lc-coast 0.005
```

| Flag | Meaning | Default |
|------|---------|---------|
| `--lc-ocean` | Offshore element size (degrees) | 0.1 (~11 km) |
| `--lc-coast` | Near-coast element size (degrees) | 0.005 (~550 m) |
| `--simplify-tolerance` | Land boundary simplification (degrees) | 0.005 |

---

## Step 4: Interpolate Bathymetry

Interpolate GEBCO depths onto every mesh node:

```bash
make bathymetry
```

This runs `mesh_interpolate.py` which:
1. Reads `simulation/input/mesh_philippines.msh`
2. Samples `simulation/input/gebco_philippines.tif` at each node
3. Enforces a minimum depth of 2 m
4. Writes `simulation/input/bathymetry.csv`

---

## Step 5: Prepare Tidal Boundary Conditions

### Option A: Use placeholder harmonics (no extra data needed)

The `simulation/input/tidal_forcing.py` template is pre-configured with synthetic M2, S2, K1, O1 harmonics. Skip this step.

### Option B: Extract real harmonics from FES2014

If you have FES2014 amplitude/phase NetCDF files:

```bash
docker compose run --rm thetis-shell /data/scripts/prepare_bc.py \
  --mesh /data/input/mesh_philippines.msh \
  --fes2014-dir /data/input/tides/fes2014 \
  --output /data/input/tidal_forcing.py \
  --constituents M2 S2 K1 O1
```

### Option C: Extract from TPXO9

```bash
docker compose run --rm thetis-shell /data/scripts/prepare_bc.py \
  --mesh /data/input/mesh_philippines.msh \
  --tpxo /data/input/tides/tpxo9.nc \
  --output /data/input/tidal_forcing.py \
  --constituents M2 S2 K1 O1
```

---

## Step 6: Run the Simulation

```bash
make run
```

This launches `run_thetis.py` inside Docker via `docker compose --profile simulation up`.

To run with custom parameters:

```bash
THETIS_DURATION_DAYS=7 THETIS_TIMESTEP=150 \
  docker compose --profile simulation run --rm thetis \
  python /data/scripts/run_thetis.py
```

| Env Variable | Default | Description |
|-------------|---------|-------------|
| `THETIS_MESH` | `input/mesh_philippines.msh` | Path to mesh file |
| `THETIS_BATHYMETRY` | `input/bathymetry.csv` | Path to bathymetry CSV |
| `THETIS_OUTPUT` | `output` | Output directory |
| `THETIS_DURATION_DAYS` | `30` | Simulation length in days |
| `THETIS_TIMESTEP` | `300` | Time step in seconds |
| `THETIS_TIDAL_MODULE` | `input/tidal_forcing.py` | Tidal BC module |

**Parallel run** (multi-core):

```bash
docker compose --profile simulation run --rm thetis \
  mpirun -np 8 python /data/scripts/run_thetis.py
```

Increase Docker memory if running large meshes:

```bash
# In docker-compose.yml, adjust:
deploy:
  resources:
    limits:
      cpus: "8"
      memory: 32g
```

---

## Step 7: Post-Process to GeoTIFF

```bash
make postprocess
```

This runs `postprocess.py` which:
1. Reads velocity time-series from `simulation/output/hdf5/`
2. Discards the first 2 days as spin-up
3. Computes time-averaged power density: **P = 0.5 × 1025 × U³** (W/m²)
4. Rasterizes the unstructured mesh onto a regular grid (500 m pixels)
5. Exports a Cloud-Optimized GeoTIFF to `simulation/output/tidal_power_density.tif`

Customize:

```bash
docker compose run --rm thetis-shell /data/scripts/postprocess.py \
  --input /data/output \
  --mesh /data/input/mesh_philippines.msh \
  --output /data/output/tidal_power_density.tif \
  --resolution 250 --start-day 3
```

---

## Step 8: Start the Web Visualization Stack

```bash
make up
```

This runs `docker compose up -d` for the web services (GeoServer, Flask API, Nginx, frontend).

| Service | URL | Purpose |
|---------|-----|---------|
| Frontend map | http://localhost | MapLibre GL JS interactive map |
| GeoServer | http://localhost:8080/geoserver | WMS/WMTS tile serving |
| Flask API | http://localhost:5000/api | REST metadata, query, download |

### Configure GeoServer (one-time, manual)

1. Open http://localhost:8080/geoserver (login: `admin` / `geoserver`)
2. Create workspace: **phil_tidal_energy**
3. Add GeoTIFF store → point to `file:data/phil_tidal_energy/tidal_power_density.tif`
4. Publish the layer with default style
5. Apply a color-ramp SLD style (blue → cyan → yellow → red)

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/layers` | GET | List available layers with metadata |
| `/api/layers/tidal_power_density` | GET | Layer stats (bbox, min/max/mean) |
| `/api/query?lat=12.8&lon=122.5` | GET | Power density at a point |
| `/api/download?layer=tidal_power_density&format=tif` | GET | Download GeoTIFF |
| `/api/health` | GET | Service health check |

### Stop the Web Stack

```bash
make down
```

---

## Quick Reference: Makefile Targets

```bash
make help        # Show all available targets

# --- Data Preparation ---
make data-dirs          # Create required directories
make download-gadm      # Download Philippines GADM shapefile

# --- Mesh & Bathymetry ---
make mesh               # Generate Gmsh mesh from shapefile
make bathymetry         # Interpolate GEBCO depths onto mesh nodes

# --- Docker Builds ---
make build              # Build thetis Docker image
make build-api          # Build Flask API Docker image

# --- Simulation ---
make shell              # Open interactive thetis shell inside container
make run                # Run tidal simulation
make postprocess        # Post-process results to GeoTIFF COG

# --- Web Stack ---
make up                 # Start web visualization (geo + api + nginx)
make down               # Stop web stack
make logs               # Tail all service logs

# --- Cleanup ---
make clean              # Remove Docker containers/images (all profiles)
make clean-data         # Remove all simulation output/input data
```

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| `make build` fails after 20+ min | Firedrake installer timed out or network issue | Retry: `make build`. Use wired connection. |
| Gmsh segfault during mesh generation | Land boundary too complex | Increase `--simplify-tolerance` (e.g., `--simplify-tolerance 0.01`). Reduce `--lc-coast`. |
| Firedrake import error in container | Virtualenv not activated | The Docker entrypoint auto-activates via `/opt/firedrake/bin/python`. Run scripts with `docker compose run --rm thetis-shell python ...` |
| PETSc/SLEPc MPI errors | Insufficient shared memory | Add `--shm-size=2g` to `docker run`, or set `shm_size: "2gb"` in `docker-compose.yml` |
| Simulation runs out of memory | Mesh too fine or too many MPI processes | Reduce mesh resolution (increase `--lc-ocean`/`--lc-coast`). Use fewer MPI procs. |
| `No space left on device` during simulation | HDF5 output accumulating | Reduce `simulation_export_time` in `run_thetis.py`. Or mount output to external drive. |
| GeoServer won't display the layer | COG not found or broken | Verify `simulation/output/tidal_power_density.tif` exists and is readable. Check GeoServer logs: `docker compose logs geoserver`. |
| Flask API returns 404 for query | GeoTIFF not generated yet | Run `make postprocess` first. Verify path mounted at `/data` in `docker-compose.yml`. |
| CORS errors in browser | GeoServer CORS not enabled | Set `CORS_ENABLED=true` in `docker-compose.yml` geoserver env. Or use nginx proxy (`/geoserver/` → GeoServer). |
| Frontend loads but no map tiles | GeoServer layer not configured | Complete the manual GeoServer setup in Step 8. Verify WMTS URL in `frontend/index.html`. |
