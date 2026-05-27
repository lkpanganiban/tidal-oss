.PHONY: help build build-api shell run stop clean clean-data

# ---- Default target ----
help:
	@echo "tidal-oss — Philippine Tidal Current Energy Assessment"
	@echo ""
	@echo "Setup:"
	@echo "  make data-dirs        Create required data directories"
	@echo "  make download-gebeo   Download GEBCO 2024 bathymetry (requires AOI URL)"
	@echo "  make download-gadm    Download Philippines GADM shapefile"
	@echo ""
	@echo "Mesh:"
	@echo "  make mesh             Generate Gmsh mesh from shapefile"
	@echo "  make bathymetry       Interpolate GEBCO depths onto mesh nodes"
	@echo ""
	@echo "Simulation:"
	@echo "  make build            Build thetis Docker image"
	@echo "  make shell            Open interactive thetis shell"
	@echo "  make run              Run tidal simulation (docker compose)"
	@echo "  make postprocess      Post-process results to GeoTIFF"
	@echo ""
	@echo "Web:"
	@echo "  make up               Start web visualization stack"
	@echo "  make down             Stop web visualization stack"
	@echo "  make build-api        Build API Docker image"
	@echo ""
	@echo "Cleanup:"
	@echo "  make clean            Remove Docker containers and images"
	@echo "  make clean-data       Remove all simulation data"
	@echo ""

# ---- Data preparation ----
data-dirs:
	mkdir -p simulation/{input,output,scripts} \
	         geoserver_data/data/phil_tidal_energy \
	         frontend

download-gadm:
	@echo "Downloading Philippines GADM boundaries..."
	mkdir -p simulation/input/shapefile
	curl -L -o simulation/input/shapefile/gadm41_PHL_shp.zip \
		"https://geodata.ucdavis.edu/gadm/gadm4.1/shp/gadm41_PHL_shp.zip" 2>/dev/null || \
		@echo "Manual download required: https://gadm.org/download_country_v3.html"
	unzip -o simulation/input/shapefile/gadm41_PHL_shp.zip -d simulation/input/shapefile/

download-gebeo:
	@echo "Downloading GEBCO 2024 for Philippine AOI..."
	@echo "Using gebco download tool: https://download.gebco.net/"
	@echo "Manually download with bbox: 116W,4S,130E,22N → place in simulation/input/GEBCO_2024.nc"

# ---- Mesh generation ----
mesh:
	docker compose run --rm thetis-shell /data/scripts/generate_mesh.py \
		--shapefile /data/input/shapefile/gadm41_PHL_0.shp \
		--output /data/input/mesh_philippines.msh \
		--lc-ocean 0.1 --lc-coast 0.005

bathymetry:
	docker compose run --rm thetis-shell /data/scripts/mesh_interpolate.py \
		--mesh /data/input/mesh_philippines.msh \
		--gebco /data/input/gebco_philippines.tif \
		--output /data/input/bathymetry.csv

# ---- Docker builds ----
build:
	docker compose build thetis

build-api:
	docker compose build flask-api

# ---- Simulation ----
shell:
	docker compose run --rm thetis-shell /bin/bash

run:
	docker compose --profile simulation up thetis

postprocess:
	docker compose run --rm thetis-shell /data/scripts/postprocess.py \
		--input /data/output \
		--output /data/output/tidal_power_density.tif \
		--resolution 500

# ---- Web stack ----
up:
	docker compose up -d nginx geoserver flask-api

down:
	docker compose down

logs:
	docker compose logs -f

# ---- Cleanup ----
clean:
	docker compose --profile simulation down -v --rmi local

clean-data:
	rm -rf simulation/output/* simulation/input/*.csv simulation/input/*.msh
