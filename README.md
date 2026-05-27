# Tidal Current Energy Assessment — Open-Source Workflow

Compute and visualize tidal-current energy potential using a fully open-source geospatial and hydrodynamic modelling stack.

- **Modelling engine:** [Thetis](https://thetisproject.org/) (Python-based 2D shallow-water solver on [Firedrake](https://firedrakeproject.org/))
- **Mesh generator:** [Gmsh](https://gmsh.info/) (open-source finite-element mesh generator)
- **Bathymetry:** [GEBCO 2024](https://www.gebco.net/data_and_products/gridded_bathymetry_data/) (15 arc-second)
- **Land boundary:** [GADM](https://gadm.org/) or [OSM](https://download.geofabrik.de/asia/philippines.html) shapefile
- **Web stack:** Flask + GeoServer + MapLibre GL JS

## Architecture

```
Phase A: Hydrodynamic Modelling                 Phase B: Web Visualization
═══════════════════════════════                 ═══════════════════════════

 GEBCO  ──┐
 GADM  ──┤ ── Gmsh ── Thetis (Firedrake)       ┌─ GeoServer (WMS/WMTS)
 FES2014 ─┘            (Docker container)     ──┤ ├─ Flask API (REST)
                                    │           │ └─ MapLibre GL JS
                             Post-processing    └─ Nginx (frontend)
                                    │
                             tidal_power.tif
```

[Full workflow diagram](docs/workflow.drawio) | [Detailed plan](docs/plan.md) | [Step-by-step run guide](src/README.md)

## Project Structure

```
.
├── src/                        # All source code, Docker configs, and scripts
│   ├── docker/
│   │   ├── Dockerfile.thetis   # Thetis/Firedrake container
│   │   └── Dockerfile.api      # Flask API container
│   ├── simulation/
│   │   ├── scripts/            # Mesh generation, simulation, post-processing
│   │   ├── input/              # Simulation input files (mesh, bathymetry, BC)
│   │   └── output/             # Simulation results → GeoTIFF
│   ├── api/                    # Flask REST API
│   ├── frontend/               # MapLibre GL JS map
│   ├── geoserver_data/         # GeoServer data directory
│   ├── nginx.conf              # Reverse proxy config
│   ├── docker-compose.yml      # Full stack orchestration
│   └── Makefile                # Convenience targets
├── docs/
│   ├── plan.md                 # Detailed implementation plan
│   └── workflow.drawio         # Visual workflow diagram
├── README.md                   # This file
└── LICENSE
```

## Quick Links

| What | Where |
|------|-------|
| Run the simulation | [src/README.md](src/README.md) |
| Understand the design | [docs/plan.md](docs/plan.md) |
| REST API endpoints | [src/api/app.py](src/api/app.py) |

## Prerequisites

| Tool | Minimum Version |
|------|----------------|
| Docker | 24+ |
| Docker Compose | v2+ |
| Gmsh | 4.12+ (or use the Gmsh Python API in Docker) |
| Python | 3.10+ (or use Docker for everything) |
| GDAL | 3.8+ (for local data prep only) |
| QGIS | 3.34+ LTR (for shapefile inspection only) |

## Alternative Modelling Engines

| Engine | Language | When to Use |
|--------|----------|-------------|
| **Thetis** (default) | Python / Firedrake | Regional-to-coastal 2D tidal models, native Gmsh support |
| **ANUGA** | Python | Small domains, rapid prototyping, simpler setup |
| **FVCOM** | Fortran 90 | Estuarine/coastal with strong wetting-drying dynamics |
| **SCHISM** | Fortran 90 | Multi-scale 3D baroclinic models |

## Validation

- Compare water levels against [NAMRIA](https://www.namria.gov.ph/) tide gauges or [IOC sea-level stations](https://www.ioc-sealevelmonitoring.org/).
- Validate currents against published ADCP campaigns or [TPXO predictions](https://www.tpxo.net/).
- Cross-check hotspots against known tidal-energy sites (San Bernardino Strait, Surigao Strait).
- Mesh convergence study: refine resolution in high-gradient areas and confirm results stabilize.

## License

MIT License — see [LICENSE](LICENSE).

## Contributing

1. Fork the repository.
2. Create a feature branch.
3. Submit a pull request with a clear description of changes.

For major changes, open an issue first to discuss what you would like to change.
