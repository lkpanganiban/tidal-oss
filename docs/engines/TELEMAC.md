# TELEMAC-2D refinement backend

This document explains how to use [TELEMAC-2D](https://opentelemac.org/) as an
*alternative* hydrodynamic engine alongside the Python screening model. The
Python solver remains the default; TELEMAC refines the screening hotspots at
higher resolution on an unstructured finite-element mesh.

> **Design rule:** TELEMAC runs **only** through a public Docker image. The
> repository never compiles TELEMAC itself. The image is pinned in
> `src/model/config.yaml` (`telemac2d.image`) so studies are reproducible.

## Why TELEMAC is an alternative, not a replacement

| Aspect | Python screening (`engine: python`) | TELEMAC-2D (`engine: telemac2d`) |
|--------|-------------------------------------|----------------------------------|
| Grid | Structured Arakawa C-grid | Unstructured triangular finite-element |
| Domain | Whole Philippine archipelago (~2 km) | One hotspot region (hundreds of metres) |
| Purpose | Locate energetic straits fast | High-fidelity local assessment |
| Runtime | Native Python (NumPy) | Public Docker image (`telemac2d.py`) |
| Outputs | `results.nc` + GeoTIFFs + GeoJSON | **same canonical products** (post-processed) |

Both engines produce the *identical* output contract consumed by the Flask /
MapLibre web application, so switching engines never breaks visualisation.

## Docker image

The default image is `flussplan/telemac:v8-latest` (Debian-based, Open MPI,
METIS, HDF5, MED). Other public images you can pin instead:

* `simvia/opentelemac:latest`
* `jamal919/telemac:v8p2r1`

> Pin by **tag or digest**, never `latest`, for reproducible studies:
>
> ```yaml
> telemac2d:
>   image: flussplan/telemac@sha256:<digest>
> ```

If you need a repository-owned build (e.g. for air-gapped or ARM hosts), fork
one of the public image Dockerfiles and build it locally; the runner only needs
`telemac2d.py` on `PATH` inside the container.

### Architecture / Apple Silicon note

`flussplan/telemac` is published for `linux/amd64`. On Apple Silicon, run it
with Rosetta emulation:

```bash
docker run --rm --platform linux/amd64 flussplan/telemac:v8-latest telemac2d.py --help
```

## Installation (Docker only)

No local TELEMAC install is required. Install Docker (24+) and Docker Compose
v2+. Pull the image once:

```bash
docker pull flussplan/telemac:v8-latest
```

## End-to-end workflow

```
screening (python)  -->  hotspots.geojson
        |
        v
cluster hotspots  -->  cases/region-001/{mesh.slf, mesh.cli, mesh.liq, case.cas, manifest.json}
        |
        v   (docker run flussplan/telemac telemac2d.py case.cas)
TELEMAC-2D  -->  cases/region-001/r2d.slf
        |
        v
postprocess  -->  output/telemac/region-001/{results.nc, *.tif, hotspots.geojson}
        |
        v
web (Flask + MapLibre)  serves the refinement exactly like the screening view
```

### Option A — one command (host with Docker)

```bash
scripts/telemac_pipeline.sh
```

This runs, in order: Python screening → hotspot clustering → TELEMAC runs →
post-processing, all via Docker Compose.

### Option B — step by step with Compose

```bash
# 1. Screening (writes output/hotspots.geojson)
docker compose up --abort-on-container-exit tidal-screening

# 2. Cluster hotspots into cases/
docker compose run --rm tidal-prepare

# 3. Refine one region (override CASE_DIR for others)
docker compose run --rm -e CASE_DIR=/cases/region-001 tidal-telemac

# 4. Convert the .slf result into canonical outputs
docker compose run --rm tidal-postprocess
```

### Option C — Python CLI (advanced)

```bash
# build screening grid + cases
python -m model.telemac prepare --cases-dir cases

# run a single case natively (telemac2d.py on PATH) or via Docker
python -m model.telemac run --case cases/region-001 --no-docker
python -m model.telemac run --case cases/region-001            # uses Docker

# convert results
python -m model.telemac postprocess --case-dir cases/region-001 \
    --output-dir output/telemac/region-001
```

## Configuration

All TELEMAC settings live under the `telemac2d:` section of
`src/model/config.yaml`, selected with `engine.name: telemac2d`. Key keys:

| Key | Meaning |
|-----|---------|
| `image` | Public Docker image (pin it) |
| `docker` | `true` to call the image; `false` for a native `telemac2d.py` |
| `cases_dir` | Where prepared cases are written |
| `ncsize` | Open MPI partitions for parallel runs (`--ncsize`) |
| `mesh.source` | `generated` (from screening) or `supplied` (your `.slf`) |
| `mesh.resolution_m` | Target spacing for generated meshes |
| `mesh.boundary.edge_types` | Which subdomain edges are tidal (`liquid`) vs coast (`solid`) |
| `mesh.boundary.phase_speed_mps` | Optional tidal phase speed to impose a propagating (W→E) tide |
| `mesh.boundary.propagation_axis` | `lon` (default) or `lat`: direction the imposed tide travels |
| `mesh.boundary.cluster_radius_km` / `margin_km` / `max_regions` | Hotspot clustering |
| `steering.time_step` / `duration_days` | TELEMAC time discretisation |
| `steering.friction_law` / `friction_coefficient` | Bottom friction (tune to match `cd`) |
| `postprocess.output_grid_resolution_km` | Raster spacing for canonical outputs |

See `CASE_AUTHORING.md` for mesh/boundary details and
`POSTPROCESSING.md` for the output mapping.  For how the refinement is
kept consistent with the Python screening (nesting, friction harmonisation,
acceptance criteria, `reconciliation.json`), see
`RECONCILIATION.md`.

## Standing-wave caveat (why a sub-domain can show "a line of points")

A refinement box is far shorter than the M2 tidal wavelength (~1000 km). If its
two liquid (open) boundaries are forced with the harmonic phases read from GOT
at points only a few tenths of a degree apart, those phases are nearly
identical (`corr ~ 0.94`).  In-phase opposing elevations on a sub-wavelength
box sustain a **standing wave**: current antinodes at the two open ends, a
**node (≈ 0) in the middle**.  Since `power = ½ρ|U|³`, mean power vanishes in
the interior and peaks only in thin bands near the edges — which renders as a
cluster of hotspot points in a near-vertical "line" and, in the worst case,
the strongest screening hotspot can land exactly on the node.

Real strait currents come from **through-flow** driven by the tide propagating
across the region as a wave.  To reproduce this in a box you must make the
boundaries genuinely out of phase.  Two approaches:

1. **Impose a propagating phase lag** — set
   `telemac2d.mesh.boundary.phase_speed_mps` (and `propagation_axis: lon`).
   The adapter retards the boundary phase by `ω·distance/phase_speed` from the
   westernmost point, so the tide travels across the box instead of sloshing
   in place.  A slower `phase_speed_mps` (e.g. 2 m/s) makes the box hold
   roughly a half wavelength and visibly propagates the crest.  This is a
   modelling choice, not a measured value, and should be tuned per site.
2. **Orient the box along the strait axis** and open the boundaries where the
   tide truly enters/exits, leaving the coast as solid walls.

Generated meshes are built by `generate_mesh_refined`, which samples
bathymetry directly at `telemac2d.mesh.resolution_m` (default 500 m) rather
than triangulating the coarse screening grid.  `telemac2d.mesh.bathymetry_source`
chooses between `parent` (inherit the screening grid's depths and wet mask, so
the refinement reconciles with the national view — the default) and `gebco`
(native GEBCO sampling, physically finer but diverges from the parent).
See `RECONCILIATION.md` for the full nesting/reconciliation strategy.

### Liquid-boundary phase is applied per point

TELEMAC reads the `.liq` file with **one column per liquid boundary** (up to
`NUMLIQ` columns), not one column per liquid *node*; the value in each column
is applied uniformly along that boundary.  The adapter therefore writes **one
column per liquid node** (each node is its own one-point boundary) so every
node gets its own GOT/parent elevation and phase:

- The phase offset for a node is `Δt = ω · s / c` where `s` is the distance of
  the node from the reference end along the `propagation_axis` and
  `c = phase_speed_mps`.
- Without per-point columns, contiguous IPOBO grouping can pair opposite box
  edges at the same latitude into one segment and force them identically → a
  standing wave → the "line of points" artifact.  Per-point columns keep the
  boundaries genuinely out of phase, producing through-flow.

For a land-aware mesh the liquid points are discovered automatically from the
wet/dry coastline: open (non-coastal) edges become `liquid`, coastal edges
become `solid` walls.  The mesh stores `liquid_ipobo` so the boundary writer
can list the liquid nodes directly.

### Strait-aligned demonstration

`scripts/telemac_strait_config.yaml` shows a Surigao Strait refinement:

- `mesh.source: generated`, a single hotspot point (`scripts/surigao_hotspots.geojson`)
  at the real Surigao sill (**125.50°E, 9.85°N** — depth ≈ −6 m; this is the
  narrow channel between Leyte and Mindanao, *not* the open ocean at
  121.5°E, 6.1°N which was used in earlier throwaway runs).
- `edge_types: {left: liquid, top: liquid, right: solid, bottom: solid}`.  At
  this seed the eastern edge is the Mindanao coast (solid) and the south is the
  sill/land (solid); open water is to the **north** (Bohol Sea) and **west**.
  The mesh excludes land cells so the coastline reads as a solid wall and only
  the north + west edges are liquid — giving two genuine phase-lagged open
  segments (through-flow, not a single closed-end pocket).
- `propagation_axis: lat`, `phase_speed_mps: 2.0` to impose a propagating tide
  across the box rather than a sloshing mode.
- `hotspot_threshold: 0.05` (W/m²) — illustrative only, because the synthetic
  0.5 m tide yields a modest peak power density (≈ 0.6 W/m²).  Raise it for
  real-survey-grade screening (the screening default is 200 W/m²).

Result (written to `output/telemac/region-001/`): a channel-shaped mesh
(72 nodes, 70 elements) that hugs the coast, **rasterised output masked to the
mesh footprint** (no whole-bounding-box fill), 264 hotspots distributed along
the channel.

#### Output masking fixes (v8 binary pitfalls)

Two bugs in the TELEMAC adapter were found and fixed while producing the above:

1. **`compute_ipobo` sized the Serafin `IPOBO` record by `ikle.max() + 1`**
   (`src/model/telemac/selafin.py`).  For a land-aware mesh that drops quads
   (orphan nodes), `ikle.max()` is **less** than `NPOIN − 1`, so the `IPOBO`
   record was truncated and Hermes aborted with `HERMES_INVALID_SERAFIN_FILE`.
   The function now sizes `IPOBO` to `NPOIN` (1 entry per node, 0 = interior)
   and is indexed by the 0-based node.  This also fixed a latent off-by-one in
   the `.cli` `NODE` column.
2. **`postprocess.py` accumulated `power_mean += np.nan_to_num(power)`**, which
   replaced out-of-mesh NaN with 0, so `grid.mask = np.isfinite(power_mean)`
   became all-`True` and the `tidal_power_density.tif` was filled across the
   whole bounding box (the solid-rectangle artifact).  The mask is now derived
   from `np.isfinite(speed_max)`, which carries the triangle/land mask
   correctly, so the power raster is confined to the mesh footprint.

Both `rasterize_to_grid` and `generate_mesh_from_grid` keep a `triangles`
argument / `land_shapefile` argument respectively so the mesh footprint is
honoured end-to-end.

## Licensing & trust

TELEMAC-MASCARET is distributed under the GNU GPL. Public images are
third-party; review the image's source and pin a digest before production use.
The `tidal-oss` repository only *invokes* the image — it does not redistribute
TELEMAC binaries.
