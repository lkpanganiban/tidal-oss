# Authoring TELEMAC-2D cases

This page documents the mesh, boundary, and steering conventions used by the
`src/model/telemac/` adapter so you can debug a failing run or supply your own
mesh.

## Mesh (`.slf` geometry)

The adapter writes a 2D triangular Selafin mesh (`NDP = 3`):

* **Node coordinates** are stored in **local tangent-plane metres**
  (equirectangular projection around the region centre) so that mesh spacing,
  bottom friction, Coriolis and current speeds are physically consistent.
* **Bed elevation** is written as the variable `ELEVATION Z` with
  **positive-up** sign (i.e. `-depth`), matching TELEMAC's convention.
* **`IPOBO`** is computed automatically: every node on an exterior triangle edge
  becomes a boundary point, numbered in ascending global-node order.

### Generated meshes

Built by clipping the screening structured grid to the hotspot bounding box and
triangulating each clipped cell into two triangles. Controlled by:

```yaml
telemac2d:
  mesh:
    source: generated
    resolution_m: 200.0
```

### Supplied meshes

Provide your own `.slf`:

```yaml
telemac2d:
  mesh:
    source: supplied
    supplied_mesh:
      path: data/my_site.slf
      coordinates_are_meters: true   # or false if the file is lon/lat
      lon0: 122.0                     # projection origin (needed when metres)
      lat0: 12.0
```

If the supplied mesh is already in longitude/latitude, set
`coordinates_are_meters: false`; the adapter reads node lon/lat directly.

## Boundary conditions (`.cli`)

One line per boundary point, in TELEMAC's `IPOBO` order. Codes used:

| Boundary type | `LIEBOR` | `LIUBOR`/`LIVBOR`/`LITBOR` |
|---------------|----------|----------------------------|
| Liquid (prescribed elevation) | `5` | `4` (free) |
| Solid coast / land (no-flux wall) | `2` | `2` |

Edge classification for generated meshes defaults to:

```yaml
telemac2d:
  mesh:
    boundary:
      edge_types:
        left: liquid
        right: liquid
        top: solid
        bottom: solid
```

For a tidal refinement you normally prescribe elevation on the edges that open
to the parent domain (left/right in a channel). Override `edge_types` per site.
For supplied meshes you can instead list explicit liquid boundary-point numbers
(1-based, in `IPOBO` order) in a JSON file and set
`boundary.liquid_nodes_file: data/my_liquid_points.json` (a JSON array of ints).

## Liquid boundary file (`.liq`)

Written only for the liquid boundary points, in the same `IPOBO` order. Default
`NLIQ = 1` (prescribed elevation). Each line is
`TIME v1 v2 … v_nliquid`. The elevation time series is reconstructed from the
**same** harmonic constituents used by the screening model
(`tidal_forcing.source` / `constituents`), so the refinement is one-way nested
in the parent run.

To also prescribe velocity, set `NLIQ = 2` and extend `mesh.liq` (advanced — edit
`src/model/telemac/boundaries.py`).

## Steering file (`.cas`)

Generated from `telemac2d.steering:`. Supported keys:

| Key | Default | Notes |
|-----|---------|-------|
| `time_step` | `30.0` | seconds |
| `duration_days` | `15` | one spring–neap cycle |
| `variables` | `['ELEVATION Z','VELOCITY U','VELOCITY V']` | requested in results |
| `friction_law` | `2` | Strickler; see note below |
| `friction_coefficient` | `40.0` | law-specific |
| `linear_friction_coefficient` | `null` | used when your build supports linear drag |
| `advection` | `false` | non-linear advection |

> **Friction matching:** the screening model uses a *linear* bottom drag
> coefficient `cd` (~0.0025). To reproduce it in TELEMAC, either set
> `FRICTION LAW : 0` + `LINEAR FRICTION COEFFICIENT : <cd>` (if your build
> honours it) or calibrate `friction_coefficient` for law 2/3. This is the main
> calibration knob between the two engines.

### Custom template

Set `steering.template` to a `.cas` file. The adapter substitutes
`{{GEOMETRY}}`, `{{BOUNDARY}}`, `{{LIQUID}}`, `{{RESULTS}}`, `{{TIME_STEP}}`,
`{{NSTEPS}}`, `{{VARIABLES}}` and leaves every other keyword under your control.

## Common failure modes

* **`My work is done` never appears** — check `mesh.slf` is readable and
  `IPOBO`/connectivity are valid (use `python -m model.telemac prepare` then
  inspect `cases/region-001/mesh.clf` via a TELEMAC mesh viewer).
* **All-zero currents** — verify liquid edges actually carry elevation
  (`mesh.liq` non-constant) and that left/right are `liquid`, not `solid`.
* **`Cannot find PARTEL.PAR`** — only relevant for parallel (`--ncsize>1`)
  runs; ensure the image's MPI setup is correct or drop to `ncsize: 1`.
