#!/usr/bin/env bash
# Entry point for the TELEMAC-2D Compose service.
# Runs the steering file of the case named by CASE_DIR with NCSIZE MPI tasks.
set -euo pipefail

CASE_DIR="${CASE_DIR:-/cases/region-001}"
NCSIZE="${NCSIZE:-1}"

# Public TELEMAC images put telemac2d.py on PATH only after sourcing their
# environment file (the image entrypoint normally does this; we override it).
source "${TELEMAC_ROOT:-/opt/telemac-mascaret}/setenv.sh"

cd "$CASE_DIR"
exec telemac2d.py case.cas --ncsize="$NCSIZE"
