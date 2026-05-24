# Philippine Tidal Current Energy Assessment — Open-Source Workflow Plan

## 1. Project Overview

Compute and visualize tidal-current energy potential around the Philippines using a fully open-source geospatial and hydrodynamic modelling stack.

- **Primary output:** GeoTIFF raster layer of tidal-current power density (W/m²)
- **Modelling engine:** TELEMAC-2D (finite-element hydrodynamic solver)
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
4. Use `gadm41_PHL_0.shp` as the landmass boundary for your TELEMAC mesh.

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

| Dataset | Download Link | Post-Download Script | Final File in `telemac_data/` |
|---------|---------------|---------------------|-------------------------------|
| Bathymetry | [GEBCO 2024](https://www.gebco.net/data_and_products/gridded_bathymetry_data/gebco_2024/) | `gdal_translate` clip | `mesh/geo_philippines.slf` (after mesh interpolation) |
| Landmass | [GADM](https://gadm.org/download_country_v3.html), [Geofabrik](https://download.geofabrik.de/asia/philippines.html) | QGIS simplify → BlueKenue import | Ingested into mesh as solid boundary nodes |
| Tidal BC | [AVISO FES2014](https://www.aviso.altimetry.fr/en/data/products/auxiliary-products/global-tide-fes.html), [TPXO](https://www.tpxo.net/) | `prepare_bc.py` | `mesh/bnd_philippines.cli` |
| Manning's n | [Manning n lookup table](https://www.hec.usace.army.mil/confluence/rasdocs/ras1dtechref/6.3/steady-flow-computations/energy-losses/roughness-factors/manning-s-n-values) | Constant or raster assignment | `mesh/fonsim_philippines.slf` (optional) |

---

## 3. Phase A — Hydrodynamic Modelling (TELEMAC + QGIS)

### 3.1 Mesh Generation (QGIS + BlueKenue / SMS-compatible)

1. **Clip GEBCO** to the Philippine maritime domain (bounding box ~ 4°–22°N, 116°–130°E).
2. **Import land shapefile** into QGIS — simplify geometry to 500–1000 m tolerance.
3. **Define open-boundary arcs** along the edges of the computational domain (Pacific Ocean, South China Sea, Sulu Sea, Celebes Sea).
4. **Generate unstructured triangular mesh** using:
   - **BlueKenue** (free mesh generator) for refined coastal areas.
   - Alternative: **Gmsh** or **OceanMesh2D** (MATLAB/GNU Octave) if available.
5. **Interpolate GEBCO depths** onto mesh nodes; enforce minimum depth (e.g., 2 m to avoid wetting/drying instability).
6. **Assign node strings** (solid boundaries = land, liquid boundaries = open ocean).

### 3.2 Boundary Condition Preparation

- Extract tidal harmonics (M2, S2, K1, O1 at minimum) from FES2014 or TPXO9 at each open-boundary node.
- Write time-series water-level BC files using Python (`pandas` + `numpy` + `xarray`).
- Convert to TELEMAC liquid boundary format (`cli` file or conlim format).

### 3.3 Docker Setup for TELEMAC-2D

TELEMAC-2D has complex Fortran/C/Python dependencies (MPI, METIS, HDF5, MED). A Docker container eliminates platform-specific build issues and ensures reproducibility.

#### 3.3.1 Project Directory Structure After Setup

```
project/
├── docker/
│   └── Dockerfile.telemac
├── telemac_data/            # All simulation I/O — mounted into the container
│   ├── mesh/
│   │   ├── geo_philippines.slf   # BlueKenue/Gmsh mesh (Selafin geometry)
│   │   ├── bnd_philippines.cli   # Boundary conditions file
│   │   └── fonsim_philippines.slf # Friction/Manning field (optional)
│   ├── input/
│   │   └── cas_philippines.cas   # TELEMAC steering file
│   ├── output/                   # Container writes results here
│   └── scripts/
│       └── prepare_bc.py         # Python script to generate .cli from FES2014
├── docker-compose.yml
└── Makefile
```

#### 3.3.2 Dockerfile for TELEMAC-2D

Create `docker/Dockerfile.telemac`:

```dockerfile
# Build stage — compile TELEMAC from source
FROM ubuntu:22.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Etc/UTC

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gfortran \
    python3 \
    python3-dev \
    python3-pip \
    python3-numpy \
    cmake \
    git \
    wget \
    libopenmpi-dev \
    openmpi-bin \
    libhdf5-dev \
    libhdf5-openmpi-dev \
    libmetis-dev \
    libscotch-dev \
    liblapack-dev \
    libblas-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# --- Step 1: Download TELEMAC v8p5r0 ---
WORKDIR /opt
RUN wget -q https://gitlab.pam-retd.fr/otm/telemac-mascaret/-/archive/v8p5r0/telemac-mascaret-v8p5r0.tar.gz \
    && tar xzf telemac-mascaret-v8p5r0.tar.gz \
    && mv telemac-mascaret-v8p5r0 telemac \
    && rm telemac-mascaret-v8p5r0.tar.gz

# --- Step 2: Write systel.cfg for gfortran + OpenMPI ---
# Adjust paths to match your container layout.
RUN mkdir -p /opt/telemac/configs && cat > /opt/telemac/configs/systel_ubuntu.cfg << 'SYSTEL'
# Configuration for Ubuntu 22.04 + gfortran + OpenMPI
[general]
sfx_zip: .gztar
sfx_lib: .a
sfx_obj: .o
sfx_mod: .mod
sfx_exe:
val_inc: -I
val_mod: -I
modules:    all
python:     python3
python_ext: python3
sr_root:    /opt/telemac
root:       /opt/telemac
version:    v8p5

[sfx_lib]
sfx_lib: .a
sfx_obj: .o

[ubuntu]
brief:      GNU gfortran + OpenMPI on Ubuntu
compilers:  gfortran
mpi_cmds:   mpif90,mpirun
cmd_obj:    gfortran -c -O3 -fconvert=big-endian -frecord-marker=4 -fPIC -cpp <mods> <incs> <f95name>
cmd_lib:    ar cru <libname> <objs>
cmd_exe:    mpif90 -fconvert=big-endian -frecord-marker=4 -fPIC -o <exename> <objs> <libs> -L/usr/lib/x86_64-linux-gnu/hdf5/openmpi -lhdf5_fortran -lhdf5 -lmetis -lz -ldl
incs_all:   -I/usr/lib/x86_64-linux-gnu/fortran/gfortran/module_files/openmpi
libs_all:   -L/usr/lib/x86_64-linux-gnu/hdf5/openmpi -lhdf5_fortran -lhdf5 -lmetis -lz -ldl
SYSTEL

# --- Step 3: Compile TELEMAC-2D ---
WORKDIR /opt/telemac
RUN python3 config.py --configs-path=configs --config=ubuntu \
    && python3 compile_telemac.py -m telemac2d

# --- Runtime stage — slim image with only what's needed ---
FROM ubuntu:22.04 AS runtime

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-numpy \
    libopenmpi3 \
    libhdf5-openmpi-103 \
    libmetis5 \
    libscotch-6.0 \
    liblapack3 \
    libblas3 \
    && rm -rf /var/lib/apt/lists/*

# Copy compiled binaries and scripts from builder
COPY --from=builder /opt/telemac /opt/telemac

ENV HOMETEL=/opt/telemac
ENV PATH=$HOMETEL/scripts/python3:$HOMETEL/builds/ubuntu/bin:$PATH
ENV PYTHONPATH=$HOMETEL/scripts/python3:$PYTHONPATH
ENV LD_LIBRARY_PATH=$HOMETEL/builds/ubuntu/lib:$HOMETEL/builds/ubuntu/wrap/lib:$LD_LIBRARY_PATH

# Entrypoint script so the user can pass telemac2d.py arguments
RUN echo '#!/bin/bash\n\
exec python3 "$@"' > /entrypoint.sh && chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["--help"]
```

#### 3.3.3 Build the TELEMAC Docker Image

```bash
# From the project root:
mkdir -p docker telemac_data/{mesh,input,output,scripts}

# Build (takes 15–45 min depending on hardware)
docker build \
  -t telemac2d:v8p5 \
  -f docker/Dockerfile.telemac \
  .

# Verify
docker run --rm telemac2d:v8p5 $HOMETEL/scripts/python3/telemac2d.py --help
```

#### 3.3.4 Verify the TELEMAC Config Inside the Container

```bash
docker run --rm telemac2d:v8p5 \
  python3 -c "import os; print(os.environ.get('HOMETEL'))"
# Expected: /opt/telemac
```

#### 3.3.5 Prepare the Simulation Input Files

Place the following inside `telemac_data/` (generate via QGIS/BlueKenue/prepare_bc.py):

| File | Description |
|------|-------------|
| `mesh/geo_philippines.slf` | Unstructured mesh geometry (nodes, elements, depths) |
| `mesh/bnd_philippines.cli` | Tidal liquid-boundary time series |
| `input/cas_philippines.cas` | TELEMAC steering (cas) file — see section 3.4 |

#### 3.3.6 Run TELEMAC-2D Simulation Inside Docker

**Single-core run (testing):**
```bash
docker run --rm \
  -v "$(pwd)/telemac_data:/data" \
  -w /data/input \
  telemac2d:v8p5 \
  $HOMETEL/scripts/python3/telemac2d.py cas_philippines.cas
```

**Multi-core run with OpenMPI (e.g., 8 cores):**
```bash
docker run --rm \
  -v "$(pwd)/telemac_data:/data" \
  -w /data/input \
  telemac2d:v8p5 \
  $HOMETEL/scripts/python3/telemac2d.py cas_philippines.cas --ncsize=8
```

**Tips for large simulations:**
- Add `--memory=32g` and `--cpus=8` to Docker flags to avoid OOM.
- Map output to a fast NVMe volume: `-v /mnt/fast_ssd:/data/output`.
- Use `--shm-size=2g` if you experience MPI shared-memory errors.

#### 3.3.7 Run Using Docker Compose (Recommended for Repeatability)

Add to `docker-compose.yml`:

```yaml
services:
  telemac2d:
    image: telemac2d:v8p5
    entrypoint: /entrypoint.sh
    command: >
      $HOMETEL/scripts/python3/telemac2d.py
      /data/input/cas_philippines.cas
      --ncsize=${TELEMAC_NPROCS:-4}
    volumes:
      - ./telemac_data:/data
    working_dir: /data/input
    environment:
      - OMPI_MCA_btl_vader_single_copy_mechanism=none
    deploy:
      resources:
        limits:
          cpus: "${TELEMAC_NPROCS:-4}"
          memory: 32g
    profiles:
      - simulation   # Only starts when explicitly requested
```

Run with:
```bash
TELEMAC_NPROCS=8 docker compose --profile simulation up telemac2d
```

#### 3.3.8 Inspect Results

Results are written to the configured output directory (set in `.cas` as `RESULTS FILE FORMAT` / `RESULTS FILE`). Typically a Selafin file (`.slf`):

```bash
ls -lh telemac_data/output/
# r2d_philippines.slf       # simulation results (2D)
# r2d_philippines_VR.slf    # validation run (if enabled)
```

Convert to NetCDF for further analysis:
```bash
docker run --rm \
  -v "$(pwd)/telemac_data:/data" \
  telemac2d:v8p5 \
  python3 $HOMETEL/scripts/python3/convert_telemac_file.py \
    /data/output/r2d_philippines.slf \
    /data/output/r2d_philippines.nc
```

#### 3.3.9 Troubleshooting Common Docker-TELEMAC Issues

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| `ImportError: No module named 'telemac'` | PYTHONPATH not set | Verify `ENV PYTHONPATH` in Dockerfile |
| `mpirun: command not found` | MPI runtime missing | Add `libopenmpi3` to runtime stage |
| `libhdf5_fortran.so: cannot open` | HDF5 linker path mismatch | Adjust `libs_all` in `systel_ubuntu.cfg` |
| `Segmentation fault` during init | Insufficient shm for MPI | Add `--shm-size=2g` to `docker run` |
| Mesh file not found | Path in `.cas` is absolute or mismatches mount | Use paths relative to `/data` in `.cas` |
| `BUILD FAILED` | systel config wrong for this Ubuntu version | Run `find /usr -name "hdf5.mod"` inside builder, update `incs_all` |

---

### 3.4 TELEMAC-2D Simulation Parameters

- **Solver:** TELEMAC-2D (depth-averaged, non-hydrostatic if needed).
- **Simulation period:** ≥ 30 days (two spring-neap cycles) for representative tidal energy assessment.
- **Time step:** CFL-limited, typically 60–300 s depending on mesh resolution.
- **Key parameters in `cas` file:**
  ```
  HYDRODYNAMIC LAW = 3 (k-epsilon) or 4 (Smagorinsky)
  TIDAL FLATS     = YES
  OPTION FOR LIQUID BOUNDARIES = 1 (prescribed elevation)
  DURATION        = 2592000  (30 days in seconds)
  ```
- **Parallel execution:** `telemac2d.py cas_file.cas --ncsize=8` (via Docker as described in 3.3.6)

### 3.5 Post-Processing & TIFF Generation

1. Convert TELEMAC result file (`slf` / Selafin) to NetCDF using `telemac2d.py` post-processing tools or `pytel` / `vtk2nc`.
2. Extract depth-averaged velocity time series (u, v) at each mesh node.
3. Compute **tidal-current power density**:
   ```
   P = 0.5 * ρ * u³       [W/m²]
   where ρ = 1025 kg/m³ (seawater density)
   ```
4. Time-average P over the full simulation period.
5. **Rasterize** the unstructured mesh result onto a regular grid (e.g., 500 m pixel):
   - Use `scipy.interpolate.griddata` or `gdal_grid`.
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
  telemac2d:
    image: telemac2d:v8p5
    entrypoint: /entrypoint.sh
    command: >
      $HOMETEL/scripts/python3/telemac2d.py
      /data/input/cas_philippines.cas
      --ncsize=${TELEMAC_NPROCS:-4}
    volumes:
      - ./telemac_data:/data
    working_dir: /data/input
    environment:
      - OMPI_MCA_btl_vader_single_copy_mechanism=none
    deploy:
      resources:
        limits:
          cpus: "${TELEMAC_NPROCS:-4}"
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
      - ./telemac_data/output:/opt/geoserver_data/data/phil_tidal_energy

  flask-api:
    build:
      context: ./api
      dockerfile: Dockerfile
    ports:
      - "5000:5000"
    volumes:
      - ./telemac_data/output:/data
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
| QGIS | 3.34+ LTR | Pre-processing, shapefile handling, mesh visualisation |
| BlueKenue / Gmsh | Latest | Unstructured mesh generation |
| TELEMAC-2D | v8p5r0 | Hydrodynamic simulation (containerized) |
| Python | 3.10+ | Data prep, post-processing, Flask API |
| `xarray`, `rioxarray` | — | NetCDF/GeoTIFF I/O |
| `scipy` | — | Interpolation |
| `gdal` | 3.8+ | Raster IO, COG creation |
| GeoServer | 2.25.2+ | WMS/WMTS tile serving |
| MapLibre GL JS | 4.x | Browser-based interactive map |
| Docker | 24+ | Container runtime for TELEMAC and all services |
| Docker Compose | v2+ | Multi-service orchestration |

---

## 6. Implementation Phases

| Phase | Duration (est.) | Deliverables |
|-------|-----------------|--------------|
| 1. Data acquisition & pre-processing | 1–2 weeks | Clipped GEBCO, simplified shoreline, open-boundary definition |
| 2. Mesh generation | 1–2 weeks | Unstructured mesh with bathymetry, boundary-node strings |
| 3. TELEMAC setup & simulation | 2–3 weeks | Calibrated model, validated tidal output |
| 4. Post-processing & COG creation | 1 week | GeoTIFF of mean tidal-current power density |
| 5. GeoServer configuration | 0.5 week | Published WMS/WMTS layers with SLD styling |
| 6. Flask API | 0.5 week | REST endpoints for metadata, query, download |
| 7. MapLibre frontend | 1 week | Interactive map with overlay, legend, popup |
| 8. Containerisation & deployment | 0.5 week | Docker Compose stack |
| 9. Documentation | 0.5 week | README, user guide, API docs |

---

## 7. Validation & Quality Assurance

- Compare TELEMAC water levels with tide-gauge data (e.g., NAMRIA stations, IOC sea-level network).
- Validate depth-averaged currents against published ADCP campaign data or TPXO predictions.
- Cross-check power-density hotspots against known tidal-energy sites (e.g., San Bernardino Strait, Surigao Strait).
- Peer-review mesh convergence by refining resolution in high-gradient areas.

---

## 8. Future Extensions

- Add TELEMAC-3D for vertical velocity profiling.
- Integrate wave-current interaction (TOMAWAC coupling).
- Extend to the entire Coral Triangle / ASEAN region.
- Add economic site-screening module (depth filter, distance-to-grid, shipping-lane exclusion).
- Real-time tidal forecast using live boundary-condition feeds.
