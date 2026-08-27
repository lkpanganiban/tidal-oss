# Refinement workflow (screening → TELEMAC-2D)

This page describes the data flow from the fast Python screening model to a
high-resolution TELEMAC-2D refinement and back to the canonical web outputs.

## Stage 1 — Screening

The Python solver (`engine: python`, the default) runs over the whole
Philippine bounding box and writes, among other files, `output/hotspots.geojson`:
point features (lon, lat, power density) for every cell above the hotspot
threshold. This is the "where to refine" signal.

```bash
python -m model.run                # or: docker compose up --abort-on-container-exit tidal-screening
```

## Stage 2 — Hotspot clustering

Screening hotspots are scattered points. A refinement case needs a contiguous
sub-domain, so `cluster_hotspots()` greedily groups points by great-circle
distance (highest-power-first), then expands each cluster by a safety margin.
Up to `max_regions` clusters are kept.

Result: `cases/regions.json` plus one case directory per region.

```bash
python -m model.telemac prepare --cases-dir cases
```

## Stage 3 — Case generation

For each region, `prepare_case()` builds a self-contained directory:

```
cases/region-001/
├── mesh.slf            # geometry (written by src/model/telemac/mesh.py)
├── mesh.cli            # boundary-condition file (liquid / solid points)
├── mesh.liq            # tidal elevation time series at liquid points
├── case.cas            # TELEMAC steering file
├── mesh_manifest.json  # projection + node lon/lat (for post-processing)
└── manifest.json       # provenance (image, steps, bbox, forcing)
```

* **Generated mesh** — the screening structured grid is clipped to the region
  bounding box and triangulated (two triangles per cell). Node coordinates are
  projected to local tangent-plane metres so physics is consistent; the
  projection origin is stored for post-processing.
* **Supplied mesh** — point `telemac2d.mesh.supplied_mesh` at your `.slf`. The
  same boundary/steering/post-processing pipeline applies; you provide the
  projection origin and (optionally) an explicit liquid-boundary point list.

## Stage 4 — TELEMAC execution

The runner mounts the case directory into the public image and invokes
`telemac2d.py case.cas`. Parallel runs pass `--ncsize`.

```bash
docker compose run --rm -e CASE_DIR=/cases/region-001 tidal-telemac
```

The solver writes `r2d.slf` (Selafin result file) into the same case directory.

## Stage 5 — Post-processing

`postprocess_case()` reads `r2d.slf`, rasterises node fields (elevation,
velocity) onto a regular lon/lat grid covering the region, computes time-mean
power density and max speed, and writes the **canonical** products:

```
output/telemac/region-001/
├── results.nc                 # NetCDF time series (eta/u/v/power)
├── tidal_power_density.tif
├── max_current_speed.tif
├── bathymetry.tif
├── distance_to_coast.tif
└── hotspots.geojson
```

These are byte-for-byte the same layers the screening model produces, so the
Flask / MapLibre web app serves them unchanged. To visualise a refinement,
point the web service at that folder:

```bash
OUTPUT_DIR=output/telemac/region-001 docker compose up -d
```

## Stage 6 — Visualisation

Open `http://localhost:5000`. All existing API endpoints (`/api/tiles`,
`/api/timeseries`, `/api/hotspots`, …) work because the output contract is
identical.

## One-shot convenience

`scripts/telemac_pipeline.sh` chains stages 1–5 for every prepared region. The
Python entry point `python -m model.run --engine telemac2d` performs the same
chain (it runs screening if hotspots are missing, then prepares, runs via
Docker, and post-processes each region).
