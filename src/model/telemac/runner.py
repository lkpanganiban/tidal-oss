"""Execute a TELEMAC-2D case via the public Docker image (or a local install).

The runner is intentionally thin: every case directory is self-contained, so we
simply mount it into the container, switch the working directory there, and
invoke ``telemac2d.py``.  Parallel runs use ``--ncsize`` for Open MPI.  When
TELEMAC is installed natively (``telemac2d.py`` on ``PATH``) the same code path
runs without Docker by passing ``docker=False``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

DEFAULT_IMAGE = "flussplan/telemac:v8-latest"
DEFAULT_WORKDIR = "/cases"


def _load_manifest(case_dir: str) -> dict:
    with open(os.path.join(case_dir, "manifest.json")) as f:
        return json.load(f)


def build_command(
    case_dir: str,
    manifest: dict,
    *,
    docker: bool,
    workdir: str = DEFAULT_WORKDIR,
) -> list[str]:
    """Return the command (list form) used to launch TELEMAC for a case."""
    image = manifest.get("image", DEFAULT_IMAGE)
    ncsize = int(manifest.get("ncsize", 1))
    cas = "case.cas"

    if docker:
        mount = f"{os.path.abspath(case_dir)}:{workdir}"
        # The public TELEMAC images (flussplan/telemac & friends) source their
        # environment via /entrypoint.sh then `exec "$@"` through `/bin/bash`.
        # Passing the launcher as a bare argument would make bash interpret the
        # Python script as shell — so wrap the invocation in `bash -c` and let
        # the entrypoint's env (PATH -> scripts/python3) resolve telemac2d.py.
        inner = [
            "-c",
            f"cd {workdir} && telemac2d.py {cas} --ncsize={ncsize}",
        ]
        return ["docker", "run", "--rm", "-v", mount, "-w", workdir, image, *inner]
    return ["telemac2d.py", cas, f"--ncsize={ncsize}"]


def run_case(
    case_dir: str,
    config: dict | None = None,
    *,
    docker: bool = True,
    dry_run: bool = False,
) -> subprocess.CompletedProcess:
    """Run one prepared TELEMAC case; returns the subprocess result.

    Raises ``FileNotFoundError`` if the case directory or manifest is missing,
    and ``RuntimeError`` if Docker was requested but is unavailable.
    """
    manifest = _load_manifest(case_dir)
    cmd = build_command(case_dir, manifest, docker=docker)

    if dry_run:
        return subprocess.CompletedProcess(cmd, 0, stdout=" ".join(cmd))

    if docker:
        which = subprocess.run(
            ["docker", "info"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if which.returncode != 0:
            raise RuntimeError(
                "Docker is not available; set docker=False to use a local TELEMAC install"
            )

    print(f"[telemac] running: {' '.join(cmd)}", file=sys.stderr)
    result = subprocess.run(cmd)
    return result


def run_all(
    cases_dir: str, *, docker: bool = True, dry_run: bool = False
) -> list[subprocess.CompletedProcess]:
    """Run every prepared case found under ``cases_dir``."""
    results = []
    for entry in sorted(os.listdir(cases_dir)):
        case_dir = os.path.join(cases_dir, entry)
        if os.path.isfile(os.path.join(case_dir, "manifest.json")):
            results.append(run_case(case_dir, docker=docker, dry_run=dry_run))
    return results
