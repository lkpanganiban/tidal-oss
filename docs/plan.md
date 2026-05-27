# Philippine Tidal Current Energy Assessment — Open-Source Workflow Plan

## 1. Project Overview

Compute and visualize tidal-current energy potential around the Philippines using a fully open-source geospatial and hydrodynamic modelling stack.

- **Primary output:** GeoTIFF raster layer of tidal-current power density (W/m²)
- **Modelling engine:** Thetis (Python-based 2D shallow-water solver built on Firedrake)
- **Alternative engines:** ANUGA (pure-Python 2D solver), FVCOM (Fortran unstructured-grid model)
- **Mesh generator:** Gmsh (open-source finite-element mesh generator)
- **Bathymetry source:** GEBCO 2024 global grid (15 arc-second)
- **Land boundary:** Philippines landmass shapefile (e.g., GADM)
- **Web stack:** Flask + GeoServer + MapLibre GL JS + COG/Tile service

---

## 2. Data Inventory & Preparation

### 2.1 Data Sources & Download Links

| Dataset | Source | Link | Format | Spatial Coverage | Resolution |
|---------|--------|------|--------|-----------------|------------|
| GEBCO bathymetry | GEBCO Compilation Group | [gebco.net](https://www.gebco.net/data_and_products/gridded_bathymetry_data/) | NetCDF / GeoTIFF | Global | 15 arc-sec (~450 m) |
| Philippines admin boundaries | GADM | [gadm.org](https://gadm.org/download_country_v3.html) | Shapefile / GeoPackage | Philippines (PHL) | Level 0–3 |
| Philippines coastline (alt.) | OpenStreetMap (OSM) | [osm-boundaries.com](https://osm-boundaries.com/Map) or [geofabrik.de](https://download.geofabrik.de/asia/philippines.html) | Shapefile | Philippines | — |
| FES2014 tidal constituents | AVISO+ | [aviso.altimetry.fr](https://www.aviso.altimetry.fr/en/data/products/auxiliary-products/global-tide-fes.html) | NetCDF | Global | 1/16° |
| TPXO9 tidal constituents | OSU / TPXO | [tpxo.net](https://www.tpxo.net/) | NetCDF | Global | 1/30° |
| Seabed roughness / Manning's n | Literature / NLCD-style | *No single source* | Raster or constant | AOI | Defined per zone |

### 2.2 Step-by-Step Download Instructions

#### 2.2.1 GEBCO Bathymetry

1. Go to **[gebco.net](https://www.gebco.net/data_and_products/gridded_bathymetry_data/gebco_2024/)**
2. Scroll to *"Download GEBCO_2024 Grid"*. Choose the **NetCDF** format (`GEBCO_2024.nc`, ~4 GB) — this is the global 15 arc-second grid. Alternatively, use the [GEBCO Download Tool](https://download.gebco.net/) to clip to the Philippine AOI before downloading, which produces a much smaller file.
3. **Clipping to Philippine maritime domain** (if full grid was downloaded):
   ```bash
   # Bounding box: 4°–22°N, 116°–130°E
   gdal_translate -projwin 116 22 130 4 \
     -of NetCDF \
     NETCDF:GEBCO_2024.nc:elevation \
     gebco_philippines.nc
   ```
4. Convert to GeoTIFF with land set to NoData (elevation > 0 masked):
   ```bash
   gdal_calc.py -A NETCDF:gebco_philippines.nc:elevation \
     --outfile=gebco_philippines.tif \
     --calc="where(A > 0, -9999, -A)" \
     --NoDataValue=-9999 --type=Float32
   ```

#### 2.2.2 Philippines Landmass & Boundaries

**Option A — GADM (recommended, academic-friendly license):**
1. Go to **[gadm.org/download_country_v3.html](https://gadm.org/download_country_v3.html)**
2. Select **Philippines** from the country dropdown, choose **Shapefile** format, click *Download*.
3. This gives you `gadm41_PHL_shp.zip` containing `gadm41_PHL_0.shp` (national boundary), `gadm41_PHL_1.shp` (regions), `gadm41_PHL_2.shp` (provinces).
4. Use `gadm41_PHL_0.shp` as the landmass boundary for mesh generation.

**Option B — Geofabrik OSM extract:**
```bash
wget https://download.geofabrik.de/asia/philippines-latest-free.shp.zip
unzip philippines-latest-free.shp.zip
# Use gis_osm_water_a_free_1.shp or gis_osm_coastlines_free_1.shp
```

#### 2.2.3 Tidal Constituent Data (Boundary Conditions)

**FES2014 (requires AVISO registration):**
1. Register at [aviso.altimetry.fr](https://www.aviso.altimetry.fr/en/data/products/auxiliary-products/global-tide-fes.html).
2. Download the FES2014 NetCDF files for amplitude and phase of M2, S2, K1, O1.
3. Extract harmonics at each open-boundary node using the `prepare_bc.py` script.

**TPXO9 (academic use, direct download):**
1. Go to **[tpxo.net](https://www.tpxo.net/)** → *TPXO9-atlas*.
2. Download the NetCDF binary. Extract constituents via the [OTPSnc toolbox](https://github.com/ESMG/pyPAG) or Python `xarray`.

### 2.3 Prepared Data Summary Table

| Dataset | Download Link | Post-Download Script | Final File in `simulation_data/` |
|---------|---------------|---------------------|-----------------------------------|
| Bathymetry | [GEBCO 2024](https://www.gebco.net/data_and_products/gridded_bathymetry_data/gebco_2024/) | `gdal_translate` clip | `bathymetry/gebco_philippines.tif` (raster for mesh interpolation) |
| Landmass | [GADM](https://gadm.org/download_country_v3.html), [Geofabrik](https://download.geofabrik.de/asia/philippines.html) | QGIS simplify → Gmsh ingestion | Ingested into Gmsh mesh as physical curves (solid boundary) |
| Tidal BC | [AVISO FES2014](https://www.aviso.altimetry.fr/en/data/products/auxiliary-products/global-tide-fes.html), [TPXO](https://www.tpxo.net/) | `prepare_bc.py` | `input/tidal_forcing.py` (Python callable for Thetis) |
| Manning's n | [Manning n lookup table](https://www.hec.usace.army.mil/confluence/rasdocs/ras1dtechref/6.3/steady-flow-computations/energy-losses/roughness-factors/manning-s-n-values) | Constant or raster assignment | `input/manning_field.tif` (optional) |

---

## 3. Phase A — Hydrodynamic Modelling (Gmsh + Thetis)

### 3.1 Why Thetis Over TELEMAC-2D

| Aspect | TELEMAC-2D | Thetis |
|--------|-----------|--------|
| Language | Fortran 90 + Python wrappers | Python (Firedrake/UFL backend) |
| Installation | Complex: build from source with MPI, HDF5, METIS, MED; requires systel config | `pip install thetis` (Firedrake via conda-forge or pip) |
| Mesh input | Selafin (`.slf`) via BlueKenue | Standard Gmsh (`.msh`) files |
| Configuration | `cas` steering file (proprietary format) | Python script (native Python syntax) |
| Boundary conditions | `cli` / conlim binary files | Python callables — define as functions |
| Post-processing | Selafin → NetCDF via converter tools | Direct HDF5/XDMF/VTU output |
| Learning curve | Steep — domain-specific tooling (BlueKenue, BK, Janet) | Moderate — standard Python + Firedrake API |
| Parallelism | OpenMPI (manual ncsize flag) | Automatic via PETSc backend |
| Wetting/drying | Built-in with tuning | Built-in (`WettingDrying` solver parameter) |

**Alternative fallback — ANUGA:** If Thetis is unavailable or the mesh is small, ANUGA provides an even simpler pure-Python 2D solver. It uses its own mesh generator rather than Gmsh by default, but `meshio` + `Gmsh` output can be converted. ANUGA is best for smaller domains (e.g., single strait/channel) due to performance constraints.

### 3.2 Mesh Generation with Gmsh

Gmsh generates the computational mesh from the Philippines shapefile boundary and domain extents.

#### 3.2.1 Workflow

1. **Define domain bounding box** in QGIS: 4°–22°N, 116°–130°E.
2. **Extract landmask from GADM shapefile**: clip the shapefile to the domain extent, simplify geometry to 250–500 m tolerance (use QGIS *Simplify* or `ogr2ogr -simplify`).
3. **Write Gmsh `.geo` script** that:
   - Defines the outer open-boundary polygon (domain edges).
   - Embeds the landmass polygon(s) as holes / solid boundaries.
   - Assigns physical group tags: `1` = open ocean boundaries, `2` = land boundaries, `3` = domain interior.
   - Sets mesh size fields: coarser (~5–10 km) in deep ocean, finer (~500 m–2 km) near coastlines and straits.
4. **Generate the mesh**:
   ```bash
   gmsh -2 -format msh2 mesh_philippines.geo -o mesh_philippines.msh
   ```
   - `-2`: 2D mesh (triangular elements).
   - `-format msh2`: compatible with `meshio` / Firedrake reader.
   - Optionally use `-algo` flags to set Delaunay (`-algo meshadapt`) or Frontal-Delaunay (`-algo del2d`).

#### 3.2.2 Gmsh `.geo` Script Template

```c
// mesh_philippines.geo
// Outer domain boundary (ocean): 116°–130°E, 4°–22°N
lc_ocean = 0.1;   // ~10 km at equator
lc_coast = 0.005; // ~500 m near land

Point(1) = {116, 4,  0, lc_ocean};
Point(2) = {130, 4,  0, lc_ocean};
Point(3) = {130, 22, 0, lc_ocean};
Point(4) = {116, 22, 0, lc_ocean};

Line(1) = {1, 2}; Line(2) = {2, 3};
Line(3) = {3, 4}; Line(4) = {4, 1};

Curve Loop(1) = {1, 2, 3, 4};

// Import simplified land boundary (pre-saved as a Gmsh-compatible polygon)
// Use QGIS or ogr2ogr to convert shapefile to Gmsh point/line format
// ... land boundary points and lines with lc_coast ...

Plane Surface(1) = {1};  // outer boundary minus land holes

Physical Curve(1) = {1, 2, 3, 4};  // open ocean boundaries (tag: 1)
Physical Curve(2) = {/* land line IDs */};  // land boundaries (tag: 2)
Physical Surface(3) = {1};          // domain interior (tag: 3)
```

#### 3.2.3 Interpolate Bathymetry onto Mesh Nodes

After mesh generation, interpolate GEBCO depths onto each mesh node using Python:

```python
import meshio
import rioxarray
from scipy.interpolate import RegularGridInterpolator

mesh = meshio.read("mesh_philippines.msh")
nodes = mesh.points[:, :2]  # lon, lat

gebco = rioxarray.open_rasterio("gebco_philippines.tif").squeeze()
interp = RegularGridInterpolator(
    (gebco.y.values[::-1], gebco.x.values),
    gebco.values[::-1, :],
    bounds_error=False, fill_value=None
)
depths = interp(nodes[:, ::-1])  # flip to (lat, lon) if needed
depths = np.maximum(depths, 2.0)  # enforce minimum depth (2 m)

np.savetxt("input/bathymetry_nodes.csv", depths, delimiter=",")
```

### 3.3 Thetis Setup & Configuration

Thetis is a Python library — no Docker build stage or Fortran compilation needed. A lightweight Docker container (or conda env) with Firedrake is sufficient.

#### 3.3.1 Environment Setup

**Option A — Conda (recommended for macOS/Linux):**
```bash
conda create -n thetis_env python=3.11
conda activate thetis_env
conda install -c conda-forge firedrake
pip install thetis meshio rioxarray xarray scipy
```

**Option B — Pip (for Docker, see 3.3.2):**
```bash
pip install firedrake thetis meshio rioxarray xarray scipy
# Note: Firedrake requires PETSc — use the firedrake-install script if pip fails
curl -O https://raw.githubusercontent.com/firedrakeproject/firedrake/master/scripts/firedrake-install
python3 firedrake-install
```

#### 3.3.2 Project Directory Structure

```
project/
├── simulation_data/
│   ├── mesh/
│   │   ├── mesh_philippines.geo    # Gmsh geometry script
│   │   └── mesh_philippines.msh    # Generated mesh
│   ├── bathymetry/
│   │   ├── gebco_philippines.tif   # Clipped GEBCO raster
│   │   └── bathymetry_nodes.csv    # Interpolated depths at nodes
│   ├── input/
│   │   ├── tidal_forcing.py        # Tidal BC function (Python callable)
│   │   ├── manning_field.tif       # Manning's n raster (optional)
│   │   └── run_thetis.py           # Main simulation script
│   ├── output/                     # Simulation results written here
│   └── scripts/
│       ├── prepare_bc.py           # Extract tidal harmonics from FES2014/TPXO
│       └── mesh_interpolate.py     # Interpolate GEBCO onto mesh
├── docker/
│   └── Dockerfile.thetis
├── docker-compose.yml
└── Makefile
```

#### 3.3.3 Dockerfile for Thetis

```dockerfile
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive \
    FIREDRAKE_DIR=/opt/firedrake

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-dev \
    build-essential gfortran \
    libopenmpi-dev openmpi-bin \
    liblapack-dev libblas-dev \
    git curl wget \
    && rm -rf /var/lib/apt/lists/*

# Install Firedrake + Thetis via the firedrake-install script
RUN curl -O https://raw.githubusercontent.com/firedrakeproject/firedrake/master/scripts/firedrake-install \
    && python3 firedrake-install --install thetis --honour-pythonpath

# Ensure Firedrake virtualenv is active
RUN echo "source /opt/firedrake/bin/activate" >> ~/.bashrc

# Install additional Python packages for data processing
RUN /opt/firedrake/bin/python -m pip install meshio rioxarray xarray scipy gdal

WORKDIR /data
ENV PATH="/opt/firedrake/bin:$PATH"
```

Build the image:
```bash
docker build -t thetis:v1 -f docker/Dockerfile.thetis .
```

#### 3.3.4 Simulation Script (`run_thetis.py`)

```python
import numpy as np
from thetis import *
from firedrake import *

# ---- 1. Read mesh ----
mesh2d = Mesh("mesh/mesh_philippines.msh")

# ---- 2. Bathymetry ----
# Load pre-interpolated depths from CSV
depth_data = np.loadtxt("bathymetry/bathymetry_nodes.csv")
P1_2d = FunctionSpace(mesh2d, "CG", 1)
bathymetry = Function(P1_2d, name="Bathymetry")
bathymetry.dat.data[:] = depth_data

# ---- 3. Setup solver ----
solver_obj = solver2d.FlowSolver2d(mesh2d, bathymetry)
options = solver_obj.options
options.simulation_export_time = 1800.0        # export every 30 min
options.simulation_end_time = 30 * 24 * 3600   # 30 days
options.timestepper_type = "CrankNicolson"
options.timestep = 300.0                       # 5 min timestep
options.output_directory = "output"

# Enable wetting & drying
options.wetting_and_drying = True

# Turbulence: Smagorinsky
options.use_smagorinsky_viscosity = True
options.smagorinsky_coefficient = Constant(0.1)

# Bottom friction: Manning's n
manning = Function(P1_2d, name="Manning")
manning.assign(Constant(0.025))  # constant value; or interpolate from raster
options.manning_drag_coefficient = manning

# ---- 4. Boundary conditions ----
# Physical tags from Gmsh: 1 = open ocean, 2 = land
# Tide forcing function (see tidal_forcing.py)
from tidal_forcing import tidal_elevation

solver_obj.bnd_functions["shallow_water"] = {
    1: {"elev": tidal_elevation},   # open boundary: prescribed tidal elevation
    2: {"un": Constant(0.0)}        # land boundary: no-normal flow
}

# ---- 5. Initial condition (cold start) ----
solver_obj.assign_initial_conditions(elev=Constant(0.0), uv=Constant((0.0, 0.0)))

# ---- 6. Run ----
solver_obj.iterate()
```

#### 3.3.5 Tidal Boundary Condition Script (`tidal_forcing.py`)

```python
import numpy as np
import xarray as xr
from firedrake import Constant, exprc
from ufl import sin, cos

# Tidal constituents extracted from FES2014 or TPXO9 via prepare_bc.py
# Each tuple: (name, amplitude_m, phase_deg, angular_speed_rad_s)
CONSTITUENTS = {
    "M2": ("M2", 0.52, 120.0, 1.405189e-04),
    "S2": ("S2", 0.23, 145.0, 1.454441e-04),
    "K1": ("K1", 0.31, 210.0, 7.292116e-05),
    "O1": ("O1", 0.25, 195.0, 6.759774e-05),
}

def tidal_elevation(x, y, t):
    """Return tidal elevation (m) at boundary node (x, y) and time t."""
    eta = 0.0
    for name, amp, phase_deg, omega in CONSTITUENTS.values():
        phase_rad = np.deg2rad(phase_deg)
        eta += amp * cos(omega * t - phase_rad)
    return eta
```

#### 3.3.6 Run Thetis

**Local (conda env):**
```bash
conda activate thetis_env
cd simulation_data
python input/run_thetis.py
```

**Docker:**
```bash
docker run --rm -it \
  -v "$(pwd)/simulation_data:/data" \
  -w /data \
  thetis:v1 \
  python input/run_thetis.py
```

**Multi-core (Docker with MPI):**
```bash
docker run --rm -it \
  -v "$(pwd)/simulation_data:/data" \
  -w /data \
  --cpus=8 --memory=32g --shm-size=2g \
  thetis:v1 \
  mpirun -np 8 python input/run_thetis.py
```

#### 3.3.7 Inspect Results

Results are HDF5 files in `output/`:
```bash
ls -lh simulation_data/output/
# hdf5/ directory containing elevation and velocity time-series
# diagnostics/ with energy, volume conservation, etc.
```

Convert to NetCDF for GIS:
```bash
python scripts/export_to_netcdf.py output/hdf5 output/results.nc
```

### 3.4 Simulation Parameters

- **Solver:** Thetis 2D shallow-water (depth-averaged, non-hydrostatic if needed).
- **Mesh:** Gmsh-generated unstructured triangular mesh; refined at coastlines/straits (500 m–2 km), coarse offshore (5–10 km).
- **Simulation period:** ≥ 30 days (two spring-neap cycles) for representative tidal energy assessment.
- **Time step:** CFL-limited, typically 150–600 s depending on mesh resolution.
- **Key parameters in `run_thetis.py`:**
  ```python
  options.timestepper_type = "CrankNicolson"   # semi-implicit, stable
  options.use_smagorinsky_viscosity = True      # turbulence closure
  options.wetting_and_drying = True             # tidal flats
  options.manning_drag_coefficient = manning    # bottom friction
  options.simulation_end_time = 30 * 24 * 3600  # 30 days
  ```
- **Parallel execution:** Via PETSc backend — `mpirun -np 8 python run_thetis.py` (see 3.3.6).

### 3.5 Post-Processing & TIFF Generation

1. Read Thetis HDF5 output using `xarray` or `h5py`.
2. Extract depth-averaged velocity time series (u, v) at each mesh node.
3. Compute **tidal-current power density**:
   ```
   P = 0.5 * ρ * u³       [W/m²]
   where ρ = 1025 kg/m³ (seawater density)
   u = sqrt(u² + v²)      (velocity magnitude)
   ```
4. Time-average P over the full simulation period.
5. **Rasterize** the unstructured mesh result onto a regular grid (e.g., 500 m pixel):
   - Use `scipy.interpolate.griddata` (linear interpolation) or `gdal_grid` (inverse-distance weighting).
   - Output as **Cloud-Optimized GeoTIFF (COG)** with EPSG:4326.
6. Optional: Compute additional metrics — available power density (95th percentile), capacity factor.

---

## 4. Phase B — Web Visualization Service

### 4.1 Architecture

```
┌──────────────┐     ┌──────────────┐     ┌─────────────────┐
│  MapLibre    │────▶│   GeoServer  │────▶│  COG / GeoTIFF  │
│  GL JS       │     │   (WMS/WMTS) │     │  stored on disk │
│  (browser)   │     └──────────────┘     └─────────────────┘
└──────────────┘            │
       │                    ▼
       │           ┌──────────────┐
       └──────────▶│  Flask API   │
                   │  (REST)      │
                   └──────────────┘
```

| Component | Role | Technology |
|-----------|------|------------|
| Frontend map | Interactive tidal-energy layer visualization | MapLibre GL JS |
| Map tile server | Serve styled raster/vector tiles from GeoTIFF | GeoServer |
| Backend API | Metadata, time-series queries, download endpoints | Flask |
| Raster storage | COG file served directly or via GeoServer | File system / S3-compatible |
| Deployment | Containerized stack | Docker / Docker Compose |

### 4.2 GeoServer Layer Configuration

1. **Create workspace** `phil_tidal_energy`.
2. **Add GeoTIFF store** pointing to the COG output.
3. **Publish WMS/WMTS layer** with the following styling (SLD):
   - Color ramp: blue (0 W/m²) → cyan → yellow → red (high).
   - Class breaks at meaningful thresholds (e.g., 0, 50, 100, 200, 400, 800, 1600 W/m²).
4. Enable **WMS GetFeatureInfo** for click-to-query functionality.

### 4.3 Flask API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/layers` | GET | List available tidal-energy layers and metadata |
| `/api/layers/<id>` | GET | Detailed metadata (bbox, units, statistics) |
| `/api/query?lat=&lon=` | GET | Return power-density value at a point |
| `/api/download` | GET | Download GeoTIFF or CSV of results |
| `/api/timeseries?lat=&lon=` | GET | (Future) Return time-series at a node |

### 4.4 MapLibre GL JS Frontend

- **Basemap:** OpenStreetMap or Positron tiles.
- **Overlay:** WMTS/WMS layer from GeoServer for tidal power density.
- **Controls:** Layer opacity slider, legend, hover/click value popup.
- **Optional layers:**
  - Bathymetry contours (from GeoServer).
  - Philippine maritime boundaries / EEZ.
  - Points of interest (straits, channels).

### 4.5 Docker Compose Stack

```yaml
services:
  # ==== Phase A: Hydrodynamic Simulation ====
  thetis:
    image: thetis:v1
    command: python /data/input/run_thetis.py
    volumes:
      - ./simulation_data:/data
    working_dir: /data
    deploy:
      resources:
        limits:
          cpus: "8"
          memory: 32g
    shm_size: "2gb"
    profiles:
      - simulation

  # ==== Phase B: Web Visualization ====
  geoserver:
    image: docker.osgeo.org/geoserver:2.25.2
    environment:
      - CORS_ENABLED=true
      - INSTALL_EXTENSIONS=true
      - STABLE_EXTENSIONS="cog-plugin"
    ports:
      - "8080:8080"
    volumes:
      - ./geoserver_data:/opt/geoserver_data
      - ./simulation_data/output:/opt/geoserver_data/data/phil_tidal_energy

  flask-api:
    build:
      context: ./api
      dockerfile: Dockerfile
    ports:
      - "5000:5000"
    volumes:
      - ./simulation_data/output:/data
    environment:
      - FLASK_ENV=development
      - OUTPUT_DIR=/data
      - GEOSERVER_URL=http://geoserver:8080/geoserver

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
    volumes:
      - ./frontend:/usr/share/nginx/html:ro
      - ./nginx.conf:/etc/nginx/conf.d/default.conf:ro
    depends_on:
      - flask-api
      - geoserver
```

---

## 5. Software Requirements Summary

| Tool | Version | Purpose |
|------|---------|---------|
| Gmsh | 4.12+ | Unstructured triangular mesh generation from shapefile boundaries |
| Gmsh Python API (`gmsh`) | 4.12+ | Programmatic mesh generation (optional — for Python-driven `.geo` creation) |
| QGIS | 3.34+ LTR | Pre-processing, shapefile handling, mesh visualisation |
| Thetis / Firedrake | Latest | 2D shallow-water hydrodynamic simulation |
| Python | 3.10+ | Data prep, post-processing, Flask API, simulation scripting |
| `meshio` | — | Convert/read Gmsh mesh files and VTU output |
| `xarray`, `rioxarray` | — | NetCDF/GeoTIFF I/O |
| `scipy` | — | Interpolation, bathymetry sampling |
| `gdal` | 3.8+ | Raster IO, COG creation |
| GeoServer | 2.25.2+ | WMS/WMTS tile serving |
| MapLibre GL JS | 4.x | Browser-based interactive map |
| Docker | 24+ | Container runtime (optional; Thetis can run directly via conda/pip) |
| Docker Compose | v2+ | Multi-service orchestration |

### 5.1 Engine Alternatives Comparison

| Engine | Language | Gmsh Support | Complexity | Best For |
|--------|----------|-------------|------------|----------|
| **Thetis** | Python (Firedrake) | Native | Moderate | Regional-to-coastal 2D tidal models |
| **ANUGA** | Python | Via meshio conversion | Low | Small domains, rapid prototyping |
| **FVCOM** | Fortran 90 | Via SMS / OceanMesh2D | High | Estuarine/coastal with wetting-drying |
| **SCHISM** | Fortran 90 | Via SMS | High | Multi-scale 3D baroclinic |

---

## 6. Implementation Phases

| Phase | Duration (est.) | Deliverables |
|-------|-----------------|--------------|
| 1. Data acquisition & pre-processing | 1–2 weeks | Clipped GEBCO, simplified shoreline, open-boundary definition |
| 2. Mesh generation (Gmsh) | 1–2 weeks | Unstructured mesh with bathymetry, boundary physical tags |
| 3. Thetis setup & simulation | 2–3 weeks | Calibrated model, validated tidal output |
| 4. Post-processing & COG creation | 1 week | GeoTIFF of mean tidal-current power density |
| 5. GeoServer configuration | 0.5 week | Published WMS/WMTS layers with SLD styling |
| 6. Flask API | 0.5 week | REST endpoints for metadata, query, download |
| 7. MapLibre frontend | 1 week | Interactive map with overlay, legend, popup |
| 8. Containerisation & deployment | 0.5 week | Docker Compose stack |
| 9. Documentation | 0.5 week | README, user guide, API docs |

---

## 7. Validation & Quality Assurance

- Compare Thetis water levels with tide-gauge data (e.g., NAMRIA stations, IOC sea-level network).
- Validate depth-averaged currents against published ADCP campaign data or TPXO predictions.
- Cross-check power-density hotspots against known tidal-energy sites (e.g., San Bernardino Strait, Surigao Strait).
- Mesh convergence study: refine resolution in high-gradient areas and confirm results stabilize.

---

## 8. Future Extensions

- Add 3D baroclinic effects via Firedrake extensions or switch to SCHISM/FVCOM.
- Integrate wave-current interaction (custom coupling or switch to COAWST/Delft3D).
- Extend to the entire Coral Triangle / ASEAN region.
- Add economic site-screening module (depth filter, distance-to-grid, shipping-lane exclusion).
- Real-time tidal forecast using live boundary-condition feeds.
- Automated mesh generation from GADM shapefile via the Gmsh Python API (`gmsh.model.geo`).
