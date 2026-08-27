#!/usr/bin/env bash
# Full Docker-driven TELEMAC-2D refinement pipeline.
#
#   1. Python screening (produces output/hotspots.geojson)
#   2. Cluster hotspots -> TELEMAC case directories under cases/
#   3. Run every prepared case inside the public TELEMAC image
#   4. Post-process each .slf result into canonical outputs
#
# Requires Docker and the pinned TELEMAC image from src/model/config.yaml.
# Usage: scripts/telemac_pipeline.sh
set -euo pipefail

CASES_DIR="${CASES_DIR:-cases}"

echo "==> 1/4 Python screening"
docker compose up --abort-on-container-exit tidal-screening

echo "==> 2/4 Prepare TELEMAC cases"
docker compose run --rm tidal-prepare

echo "==> 3/4 Run TELEMAC cases"
for d in "$CASES_DIR"/region-*; do
  [ -f "$d/manifest.json" ] || continue
  rid="$(basename "$d")"
  echo "    running $rid"
  docker compose run --rm -e "CASE_DIR=/cases/$rid" -e "NCSIZE=${NCSIZE:-1}" tidal-telemac
done

echo "==> 4/4 Post-process results"
for d in "$CASES_DIR"/region-*; do
  [ -f "$d/manifest.json" ] || continue
  rid="$(basename "$d")"
  echo "    post-processing $rid"
  docker compose run --rm \
    tidal-postprocess \
    python -m model.telemac postprocess \
    --case-dir "/cases/$rid" \
    --output-dir "/output/telemac/$rid"
done

echo "==> Done. Refinement outputs under output/telemac/"
