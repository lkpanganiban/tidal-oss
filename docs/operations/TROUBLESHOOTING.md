# TELEMAC-2D troubleshooting

Specific issues for the Docker-based refinement workflow. For screening-model
problems see the root `README.md` troubleshooting table.

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `telemac2d.py: command not found` in container | Wrong image / entrypoint | Use an image that puts `telemac2d.py` on `PATH` (e.g. `flussplan/telemac`, `simvia/opentelemac`). Pin it in `telemac2d.image`. |
| `exec format error` / crashes on Apple Silicon | `amd64` image on ARM | Run with `--platform linux/amd64`, or build an ARM image from the upstream Dockerfile. |
| `docker: not found` from `run_model` | Docker socket not mounted / Docker not installed | Install Docker, or set `telemac2d.docker: false` and install TELEMAC natively (`telemac2d.py` on `PATH`). |
| TELEMAC run hangs / no `r2d.slf` | Missing `mesh.slf`, bad `.cli`, or zero liquid points | Inspect `cases/region-001/manifest.json` (`n_liquid_points`); verify `mesh.cli` has `LIEBOR=5` lines; open `mesh.slf` in a mesh viewer. |
| `My work is done` never prints | Solver divergence (CFL / friction) | Lower `steering.time_step`; check `friction_law`/`friction_coefficient`; ensure liquid boundaries carry non-constant elevation. |
| All currents ~0 in results | Liquid edges are `solid` | Set the correct `mesh.boundary.edge_types` (left/right = `liquid`) or supply `liquid_nodes_file`. |
| `Cannot find PARTEL.PAR` | Parallel run setup | Use `ncsize: 1`, or verify the image's MPI/partitioning config. |
| Post-process produces blank rasters | Result variables named differently | Ensure `steering.variables` includes `ELEVATION Z`, `VELOCITY U`, `VELOCITY V` (exact names). |
| Post-process `KeyError` on variables | `r2d.slf` lacks a variable | Re-run TELEMAC with the variables requested in `VARIABLES FOR GRAPHICS`. |
| Web map empty after refinement | Wrong `OUTPUT_DIR` | Start the web service with `OUTPUT_DIR=output/telemac/region-001`. |
| `mesh.liq` values all zero | Synthetic-only run or missing `tidal_forcing.path` | For real forcing set `tidal_forcing.path`; synthetic still yields a small M2 signal. |

## Verifying the image

```bash
docker run --rm flussplan/telemac:v8-latest telemac2d.py --help
```

A healthy image prints TELEMAC usage. If it errors, the tag is wrong or the
image is not pulled.

## Pinning for reproducibility

Never use `latest` in a study. Record the digest:

```bash
docker inspect --format='{{index .RepoDigests 0}}' flussplan/telemac:v8-latest
```

and set `telemac2d.image: flussplan/telemac@sha256:<digest>` in
`src/model/config.yaml`.
