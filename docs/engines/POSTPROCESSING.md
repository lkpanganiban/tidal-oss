# Post-processing TELEMAC results

`src/model/telemac/postprocess.py` turns a TELEMAC Selafin result (`r2d.slf`)
into the canonical screening outputs so the web application is engine-agnostic.

## Inputs

* `cases/<region>/r2d.slf` — result file (variables `ELEVATION Z`,
  `VELOCITY U`, `VELOCITY V`).
* `cases/<region>/mesh_manifest.json` — projection origin (`lon0`, `lat0`) and
  per-node lon/lat, written when the case was prepared.

## Algorithm

1. Read all time steps from the result file (`read_serafin`).
2. Build a regular lon/lat target grid covering the region bounding box at
   `postprocess.output_grid_resolution_km`.
3. For every time step, interpolate the unstructured node fields onto the grid
   (scipy `griddata`, linear with nearest fallback; inverse-distance if scipy
   is absent).
4. Compute speed `|U|` and power density `½·ρ·|U|³` at each node, accumulate the
   time-mean power and the max speed.
5. Write, using the existing `model.output` writers:
   * `results.nc` — streaming NetCDF (`eta`, `u`, `v`, `power_density`) with
     engine metadata so `/api/timeseries` works unchanged.
   * `tidal_power_density.tif`, `max_current_speed.tif`, `bathymetry.tif`,
     `distance_to_coast.tif` — Cloud-Optimised GeoTIFFs.
   * `hotspots.geojson` — points above `output.hotspot_threshold`.

## Output mapping

| TELEMAC result | Canonical product | Units |
|----------------|------------------|-------|
| `ELEVATION Z` (rasterised) | `results.nc` `eta`, tiles | m |
| `VELOCITY U/V` (rasterised) | `results.nc` `u`/`v`, speed tiles | m/s |
| `½·ρ·|U|³` (time-mean) | `tidal_power_density.tif` | W/m² |
| `max |U|` | `max_current_speed.tif` | m/s |
| `-ELEVATION Z` (rasterised) | `bathymetry.tif` | m (positive down) |
| mask distance | `distance_to_coast.tif` | km |

## Metadata

`results.nc` global attributes record `source: telemac2d`, the `image` tag, the
region id, duration and resolution, so downstream consumers can distinguish
refinement outputs from screening outputs.

## Running

```bash
python -m model.telemac postprocess \
    --case-dir cases/region-001 \
    --output-dir output/telemac/region-001
```

Or via Compose: `docker compose run --rm tidal-postprocess`.
