# Reconciling TELEMAC refinements with the Python screening

The Python screening model is the **nationwide view**; each TELEMAC-2D run is
the **zoomed-in, higher-resolution view of a strait or channel**.  Users will
look at the national layer first, then zoom into a refined site expecting a
*more accurate* estimate of the same feature — not a wildly different one.
This document is the recommendation set for keeping the two engines consistent,
records what is already implemented, and what remains to close the gap.

## The core principle

Treat TELEMAC as a **nested child of the screening run**, not as an independent
model.  When the child shares the parent's bathymetry, forcing and friction, the
**only** remaining difference is resolution — and the zoom view reconciles with
the national view by construction.

## Why the two models historically diverged (root causes found)

| # | Root cause | Fix (implemented) |
|---|------------|-------------------|
| 1 | `.cli` column 8 (NUMLIQ) was `4` (FREE) for every liquid point, so TELEMAC ignored the `.liq` file entirely and forced elevation to 0 → near-still water (0.07 m/s) | `write_cli` now writes the per-point liquid-boundary number; verified the M2 phase ramp is applied exactly |
| 2 | `.liq` FRLIQ layout: v8p1r1 requires line 1 = `T SL(1) …`, line 2 = skipped units line, then data — removing the units line made the reader swallow the first record ("T=30 OUT OF RANGE") | `write_liq` restores the units line |
| 3 | Contiguous IPOBO segment grouping paired *opposite* box edges at the same latitude into one segment → identical forcing → no east–west gradient | Per-point liquid boundaries (`segments = [[k] …]`) |
| 4 | Generated meshes were triangulated from the 2 km screening grid, so "refinement" reused the coarse geometry | `generate_mesh_refined` samples bathymetry at `mesh.resolution_m` (500 m) |
| 5 | Friction: `LAW OF BOTTOM FRICTION : 2` with coefficient 40 = **Chezy 40** (cf = g/C² ≈ 0.0061, 2.4× the screening drag cd = 0.0025) | Chezy coefficient `sqrt(g/cd) ≈ 62.6` |
| 6 | TELEMAC wrote a snapshot every solver step (43 201 frames) while the screening saves hourly → different aggregation windows | `GRAPHIC PRINTOUT PERIOD` set from `output.save_interval_hours` |
| 7 | Boundary tide was reconstructed from GOT + an artificial phase ramp instead of the parent's own solution | Parent nesting (`telemac/parent.py`); ramp only in the harmonic fallback |
| 8 | Post-processing rebuilt Delaunay + footprint masks per frame (30+ min/region) | `MeshRasterizer` precomputes geometry once (3 s/region) |

## Recommendation 1 — Build the TELEMAC domain around the actual strait

Inferred hotspot rectangles can cut off one end of a strait or orient the box
across the channel.  For each refined site define explicitly:

- the strait **centreline / inlet–outlet coordinates**,
- **channel width and along-channel length**,
- the **offshore buffer**,
- which box edges are **liquid** (the two ends where the tide enters/exits)
  and which are **solid** (coastline walls).

The mesh must contain the full constriction **and both connected water bodies**
so the tide can actually flow through.

**Implemented** — `telemac2d.mesh.boundary.sites` (explicit `id` / `axis`
`EW`|`NS` / `bbox`) takes precedence over hotspot clustering; regions built
from sites derive their liquid edges perpendicular to the channel axis
(`hotspots.regions_from_sites`).  Auto-clustering (`cluster_hotspots`) is
strait-aware (PCA channel axis + `channel_buffer_km`), and mesh construction
rejects domains whose liquid boundaries are not in a single wet component
(`_validate_throughflow`).

## Recommendation 2 — Use parent-model boundary conditions (one-way nesting)

Sampling the *parent's own* solution at the refinement boundary is the
definition of nesting:

1. **Elevation**: impose the screening run's hourly η at each TELEMAC liquid
   point — same constituents, epoch, datum and spatial phase.
2. **Velocity** (best practice): impose the parent's boundary flow state too
   (Thompson/characteristic treatment) so the child is not under-driven by
   elevation alone.
3. **Phase ramp**: treat `phase_speed_mps` as an explicit per-site tuning knob,
   not a default — it is only meaningful when no parent solution exists.

**Implemented** — `telemac2d.mesh.boundary.parent_results_nc: auto` samples
`<output>/results.nc` (wet-cell-aware: bilinear over water, nearest-wet
fallback near coasts, harmonic fallback per point).  The phase ramp is now
applied only in the harmonic fallback.  Elevation-only nesting raised the
refined speeds from ~1.1 m/s (harmonic) to ~1.4 m/s in the first test region.

**Experimental / remaining** — `telemac2d.mesh.boundary.thompson: true` writes
the parent's `U(i)`/`V(i)` columns and sets `OPTION FOR LIQUID BOUNDARIES : 2`,
but v8p1r1 routes prescribed-velocity boundaries through `DEBIMP` flowrate
rescaling and demands `PRESCRIBED FLOWRATES` — the feature is gated off until a
defensible per-boundary flowrate series is supplied.

## Recommendation 3 — Resolve the channel with appropriate data

Preferred bathymetry hierarchy for a refined site:

1. nautical-chart / hydrographic survey data,
2. high-resolution regional bathymetry,
3. native GEBCO (~15″ ≈ 450 m) with coastline enforcement,
4. coarse GEBCO only as a fallback.

`bathymetry_source: parent` (the default) inherits the screening grid's depths
and wet mask at mesh resolution, so the child and parent share channel depths —
maximising reconciliation.  `bathymetry_source: gebco` samples native GEBCO,
which is physically finer but makes the refined currents diverge from the
parent (the divergence is recorded in `reconciliation.json`).

## Recommendation 4 — Match the physics

- **Bottom friction**: use Chezy `C = sqrt(g / cd)` with the screening's `cd`
  (default 0.0025 → C ≈ 62.6).  Implemented in `steering.py` and
  `config.yaml` (`friction_law: 2`, `friction_coefficient: 62.6`).
- **Snapshot cadence**: hourly, matching `output.save_interval_hours`.
  Implemented (`GRAPHIC PRINTOUT PERIOD`).
- **Advection / viscosity / Coriolis**: keep parity with the screening where
  possible; if they differ, treat it as a documented modelling choice.
- **Do not** simply multiply TELEMAC power to match.  `P = ½ρ|U|³`: a small
  velocity error becomes a large power error; calibrate only defensible
  parameters (friction, viscosity, boundary treatment, bathymetry smoothing)
  against a short control run per site.

## Recommendation 5 — Compare equivalent quantities

`max-vs-max` is the harshest and most misleading comparison — it is dominated
by the parent's coarse-grid jets.  Compare like-for-like:

- the same geographic footprint and wet-area mask,
- the same time window and hourly timestamps,
- the same power formula and the same statistic (time-mean power),
- plus **distribution statistics** (median / p95 speed) in addition to the max.

**Implemented** — `output/telemac/<region>/reconciliation.json` records, for
both engines in the same bbox: max power, max speed, p95 speed, median speed,
and the ratios at all three levels.

## Recommendation 6 — Site calibration acceptance test

A refined site should be accepted only when, in the comparable channel area:

| Metric | Acceptance window |
|--------|-------------------|
| TELEMAC / parent **speed** | 0.7× – 1.5× |
| TELEMAC / parent **power** | 0.35× – 3.0× (power ∝ speed³) |

The reconciliation report assigns `status: ok | tolerable | review` from these
windows.

## Recommendation 7 — Product behaviour (web)

The nationwide and zoom layers should be presented as one nested model:

- **national scale** → screening layer (parent),
- **zoomed into a refined site** → TELEMAC layer, *only if* the site passed
  reconciliation,
- keep the parent estimate visible as a comparison — e.g. labels
  `National screening: 3 080 W/m²` / `TELEMAC refinement: 1 450 W/m²`
  (`−53%`),
- show a warning when the site is `review`/`tolerable`.

This is **not yet implemented** in `src/web/`; the reconciliation report is
written but not surfaced in the map UI.

## Current measured state (15-day runs, 500 m meshes)

| region | axis | TELEMAC max speed | TELEMAC max power | screening (same box) max speed | max power | speed ratio | power ratio | status |
|--------|------|------------------:|------------------:|-------------------------------:|----------:|------------:|------------:|--------|
| region-001 | NS | 1.14 m/s | 107 W/m² | 3.51 m/s | 3080 W/m² | 0.33 | 0.035 | review |
| region-002 | NS | 1.25 m/s | 101 W/m² | 3.66 m/s | 3053 W/m² | 0.34 | 0.033 | review |
| region-003 | NS | 1.16 m/s | 107 W/m² | 3.45 m/s | 2253 W/m² | 0.34 | 0.047 | review |

Distribution comparison (region-001): parent p95 = 1.74 m/s, median = 0.66 m/s;
refined p95 = 0.53 m/s, median = 0.07 m/s → the refined field is robustly
~2–3× slower even away from grid-scale extremes, which is consistent with the
parent's 2 km cells concentrating flow over smeared shallow depths (a
coarse-grid feature a finer model does not reproduce).

## What to do next (ordered)

1. **Complete Thompson nesting** — supply a defensible per-boundary flowrate
   series (parent transport) so `thompson: true` works in v8p1r1, and confirm
   the refined speeds rise toward the parent's.
2. **Add explicit sites** for the straits of interest (`telemac2d.mesh.boundary.sites`)
   so domains are authorable and reproducible instead of inferred.
3. **Upgrade bathymetry** for the sites that matter most (survey / regional
   data) via `telemac2d.mesh.supplied_mesh` or the GEBCO sampling path.
4. **Surface reconciliation in the web UI** (Recommendation 7).
5. **Re-calibrate** friction/boundary per site with short control runs; treat
   the parent's hotspot peaks as screening bias to investigate rather than a
   target to fit by scaling.