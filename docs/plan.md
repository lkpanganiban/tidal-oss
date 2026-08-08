# Implementation Plan

This document summarises the implementation plan for the open-source
Philippine tidal-current energy assessment workflow.  See
[`README.md`](../README.md) for quick start and
[`MODEL.md`](MODEL.md) for the physics and methodology.

## Two-phase workflow

```
Phase A: Screening                                Phase B: Web Visualization
═══════════════════════                           ═══════════════════════════

 GEBCO  ──┐
 GOT4.10c ┤ ── model.run ──┬── results.nc              Flask (REST API)
          ─┘               ├── tidal_power_density.tif  │
                           └── hotspots.geojson    MapLibre GL JS
```

1. **Phase A — screening model** (`src/model/`)
   - Load GEBCO bathymetry, clip to the Philippine bounding box, regrid to a
     uniform ~2 km Arakawa C-grid, and apply a GADM-derived land mask.
   - Read tidal harmonics (GOT4.10c / FES2014 / TPXO9, or a synthetic M2
     tide) and reconstruct the elevation time series at open-boundary cells.
   - Run the 2D depth-averaged shallow-water solver over at least one
     spring–neap cycle (15 days), enforcing the CFL stability condition.
   - Post-process: time-mean power density $P = \tfrac12 \rho |U|^3$, export
     NetCDF time series, a Cloud-Optimised GeoTIFF, and a hotspot GeoJSON
     (cells ≥ 200 W/m²).

2. **Phase B — web visualisation** (`src/web/`)
   - Flask REST API serving the GeoTIFF as colormapped raster tiles, point
     queries, layer metadata, and a GeoTIFF download.
   - MapLibre GL JS frontend with an interactive overlay, measurement tools,
     and statistics panel.

3. **Refinement (future)** — TELEMAC-2D finite-element modelling of the
   top hotspots at higher resolution, driven by the screening results.

## Milestones

- [x] 2D shallow-water solver on an Arakawa C-grid (forward-backward scheme)
- [x] GEBCO loading / regridding / land masking
- [x] Tidal boundary forcing (GOT4.10c, FES2014, TPXO9, synthetic)
- [x] Output writers: NetCDF, COG GeoTIFF, hotspot GeoJSON
- [x] Flask + MapLibre web service with tile/query/download endpoints
- [x] Validation suite (seiche period, M2 channel, mass conservation)
- [ ] TELEMAC-2D refinement workflow
- [ ] Real-time tidal forecasting via live boundary feeds
- [ ] Economic site-screening module (depth filter, distance-to-grid)
