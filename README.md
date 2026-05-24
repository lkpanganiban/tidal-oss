# Tidal Current Energy Assessment — Open-Source Workflow

Compute and visualize tidal-current energy potential using a fully open-source geospatial and hydrodynamic modelling stack.

- **Modelling engine:** [TELEMAC-2D](https://opentelemac.org/) (finite-element hydrodynamic solver)
- **Bathymetry:** [GEBCO 2024](https://www.gebco.net/data_and_products/gridded_bathymetry_data/) (15 arc-second)
- **Land boundary:** [GADM](https://gadm.org/) or [OSM](https://download.geofabrik.de/asia/philippines.html) shapefile
- **Web stack:** Flask + GeoServer + MapLibre GL JS

## Architecture

Two-phase workflow:

```
Phase A: Hydrodynamic Modelling                 Phase B: Web Visualization
═══════════════════════════════                 ═══════════════════════════
                                                                         
 GEBCO  ──┐                                                              
 GADM  ──┤ ── QGIS ── BlueKenue ── TELEMAC-2D   ┌─ GeoServer (WMS/WMTS) 
 FES2014 ─┘                  (Docker container) ─┤ ├─ Flask API (REST)   
                                      │           │ └─ MapLibre GL JS    
                               Post-processing    └─ Nginx (frontend)     
                                      │                                  
                               tidal_power.tif                           
```

[Full workflow diagram](docs/workflow.drawio) | [Detailed plan](docs/plan.md)

## Quick Start

### Prerequisites

| Tool | Minimum Version |
|------|----------------|
| Docker | 24+ |
| Docker Compose | v2+ |
| Python | 3.10+ |
| QGIS | 3.34+ LTR |
| GDAL | 3.8+ |

### 1. Clone and prepare directories

```bash
git clone <repo-url> && cd $(basename $_)
mkdir -p telemac_data/{mesh,input,output,scripts} \
         frontend \
         api \
         geoserver_data
```

### 2. Download required data

| Dataset | Download Link | Output |
|---------|--------------|--------|
| Bathymetry | [GEBCO 2024](https://www.gebco.net/data_and_products/gridded_bathymetry_data/gebco_2024/) | `GEBCO_2024.nc` |
| Landmass | [GADM Philippines](https://gadm.org/download_country_v3.html) | `gadm41_PHL_0.shp` |
| Tidal constituents | [FES2014](https://www.aviso.altimetry.fr/en/data/products/auxiliary-products/global-tide-fes.html) or [TPXO9](https://www.tpxo.net/) | NetCDF |

```bash
# Clip GEBCO to Philippine AOI
gdal_translate -projwin 116 22 130 4 \
  -of NetCDF NETCDF:GEBCO_2024.nc:elevation \
  telemac_data/gebco_philippines.nc

# Convert to bathymetry GeoTIFF (land = NoData)
gdal_calc.py -A NETCDF:telemac_data/gebco_philippines.nc:elevation \
  --outfile=telemac_data/gebco_philippines.tif \
  --calc="where(A > 0, -9999, -A)" --NoDataValue=-9999 --type=Float32

# Alternative OSM coastline
wget https://download.geofabrik.de/asia/philippines-latest-free.shp.zip
unzip philippines-latest-free.shp.zip
```

### 3. Generate the mesh (QGIS + BlueKenue)

1. Open the clipped bathymetry and landmass shapefile in QGIS.
2. Define open-boundary arcs and simplify the coastline (500–1000 m tolerance).
3. Export to [BlueKenue](https://www.nrc-cnrc.gc.ca/eng/solutions/advisory/blue_kenue_index.html) (or [Gmsh](https://gmsh.info/)) to generate an unstructured triangular mesh.
4. Interpolate depths onto mesh nodes and assign solid/liquid boundary node strings.
5. Save as `telemac_data/mesh/geo_philippines.slf`.

### 4. Run the hydrodynamic simulation

```bash
# Build the TELEMAC-2D Docker image (15–45 min)
docker build -t telemac2d:v8p5 -f docker/Dockerfile.telemac .

# Prepare boundary conditions from tidal constituents
python3 telemac_data/scripts/prepare_bc.py \
  --fes2014 /path/to/fes2014 \
  --mesh telemac_data/mesh/geo_philippines.slf \
  --output telemac_data/mesh/bnd_philippines.cli

# Run simulation (8-core MPI)
docker run --rm \
  -v "$(pwd)/telemac_data:/data" \
  -w /data/input \
  --shm-size=2g \
  telemac2d:v8p5 \
  $HOMETEL/scripts/python3/telemac2d.py cas_philippines.cas --ncsize=8

# Or via Docker Compose
TELEMAC_NPROCS=8 docker compose --profile simulation up telemac2d
```

### 5. Post-process to GeoTIFF

```bash
# Convert Selafin results to NetCDF
docker run --rm -v "$(pwd)/telemac_data:/data" telemac2d:v8p5 \
  python3 $HOMETEL/scripts/python3/convert_telemac_file.py \
    /data/output/r2d_philippines.slf \
    /data/output/r2d_philippines.nc

# Run power-density computation and rasterization
python3 scripts/postprocess.py \
  --input telemac_data/output/r2d_philippines.nc \
  --output telemac_data/output/tidal_power_density.tif \
  --resolution 500
```

### 6. Start the web visualization stack

```bash
docker compose up -d
```

| Service | URL | Purpose |
|---------|-----|---------|
| GeoServer | http://localhost:8080/geoserver | WMS/WMTS tile serving |
| Flask API | http://localhost:5000/api | REST metadata & queries |
| Frontend | http://localhost | MapLibre GL JS map |

## Project Structure

```
.
├── docker/
│   └── Dockerfile.telemac          # TELEMAC-2D build container
├── telemac_data/
│   ├── mesh/
│   │   ├── geo_philippines.slf     # Mesh geometry
│   │   ├── bnd_philippines.cli     # Boundary conditions
│   │   └── fonsim_philippines.slf  # Friction field (optional)
│   ├── input/
│   │   └── cas_philippines.cas     # TELEMAC steering file
│   ├── output/
│   │   └── tidal_power_density.tif # Final GeoTIFF output
│   └── scripts/
│       ├── prepare_bc.py           # Generate .cli from FES2014/TPXO9
│       └── postprocess.py          # SLF → NetCDF → COG
├── api/
│   ├── app.py                      # Flask REST API
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── index.html                  # MapLibre GL JS map
│   └── style.css
├── geoserver_data/                 # GeoServer data directory
│   └── data/phil_tidal_energy/     # Symlink or copy of output GeoTIFFs
├── nginx.conf                      # Nginx reverse proxy config
├── docker-compose.yml              # Full stack orchestration
├── docs/
│   ├── plan.md                     # Detailed implementation plan
│   └── workflow.drawio             # Visual workflow diagram
├── README.md
└── Makefile
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/layers` | GET | List available tidal-energy layers |
| `/api/layers/<id>` | GET | Layer metadata (bbox, units, statistics) |
| `/api/query?lat=&lon=` | GET | Power-density value at a point |
| `/api/download` | GET | Download GeoTIFF or CSV |

## Steering File Reference

Key parameters in `cas_philippines.cas`:

```
DURATION                             = 2592000
TIME STEP                            = 150
HYDRODYNAMIC LAW                     = 3
TIDAL FLATS                          = YES
OPTION FOR LIQUID BOUNDARIES         = 1
GEOMETRY FILE                        = /data/mesh/geo_philippines.slf
BOUNDARY CONDITIONS FILE             = /data/mesh/bnd_philippines.cli
RESULTS FILE                         = /data/output/r2d_philippines.slf
RESULTS FILE FORMAT                  = SELAFIN
```

## Validation

- Compare water levels against [NAMRIA](https://www.namria.gov.ph/) tide gauges or [IOC sea-level stations](https://www.ioc-sealevelmonitoring.org/).
- Validate currents against published ADCP campaigns or [TPXO predictions](https://www.tpxo.net/).
- Cross-check hotspots against known tidal-energy sites (San Bernardino Strait, Surigao Strait).

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| TELEMAC `Segmentation fault` on start | Add `--shm-size=2g` to `docker run` |
| `BUILD FAILED` in Docker | Run `find /usr -name "hdf5.mod"` inside builder and update `incs_all` in `systel_ubuntu.cfg` |
| GeoServer won't read GeoTIFF | Ensure the file is a [Cloud-Optimized GeoTIFF](https://www.cogeo.org/) with inner overviews |
| CORS errors from MapLibre | Set `CORS_ENABLED=true` in GeoServer container env |
| Flask cannot find results | Verify `telemac_data/output` is mounted at `/data` in the flask-api container |

## Future Extensions

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
