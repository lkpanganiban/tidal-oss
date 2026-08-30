#!/usr/bin/env bash
# Full Docker-driven TELEMAC-2D refinement pipeline.
#
#   1. Python screening (produces <output>/hotspots.geojson)  [auto if missing]
#   2. Cluster hotspots -> TELEMAC case directories under cases/
#   3. Run every prepared case inside the public TELEMAC image
#   4. Post-process each .slf result into canonical outputs
#
# All four stages run through the single in-process pipeline
# (src/model/run.py::run_telemac_pipeline) via `python -m model.run
# --engine telemac2d`, so no separate compose services are needed and every
# stage (screening, prepare, TELEMAC run, post-process) shares the same
# config (output.hotspot_threshold, bathymetry paths, reconciliation).
#
# Requires: the model dependencies on PATH, a working Docker daemon, and the
# TELEMAC image pinned by telemac2d.image (see src/model/config.yaml).
#
# Usage:
#   scripts/telemac_pipeline.sh [-c config.yaml]
#   CONFIG=scripts/telemac_strait_config.yaml scripts/telemac_pipeline.sh
set -euo pipefail

CONFIG="${CONFIG:-src/model/config.yaml}"
PYTHON="${PYTHON:-python}"

if [[ ":${PYTHONPATH:-}:" != *":$PWD/src:"* ]]; then
  export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
fi

echo "==> telemac2d pipeline (screening -> prepare -> run -> post-process)"
exec "$PYTHON" -m model.run --config "$CONFIG" --engine telemac2d "$@"