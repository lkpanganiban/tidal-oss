"""Command-line entry point for the TELEMAC-2D refinement backend.

Sub-commands
------------
* ``prepare``     -- cluster screening hotspots and write TELEMAC case dirs.
* ``run``         -- execute prepared case(s) inside the public Docker image.
* ``postprocess`` -- convert a ``.slf`` result into canonical outputs.
* ``pipeline``    -- prepare + run + postprocess in one shot.

The Python interpreter must be able to import ``model`` (run with
``PYTHONPATH=src`` or ``python -m model.telemac`` from the repo root).
"""

from __future__ import annotations

import argparse
import json
import os

from ..config import load_config
from ..run import build_screening_grid, prepare_regions
from .postprocess import postprocess_case
from .runner import run_all, run_case


def _build_grid(config):
    return build_screening_grid(config)


def _prepare(args, config) -> list:
    out_cfg = config["output"]
    out_dir = os.environ.get("OUTPUT_DIR") or out_cfg["dir"]
    hotspots_path = args.hotspots or os.path.join(
        out_dir, out_cfg.get("hotspots_geojson", "hotspots.geojson")
    )
    if not os.path.isfile(hotspots_path):
        raise FileNotFoundError(f"screening hotspots not found: {hotspots_path}")

    grid = _build_grid(config)
    cases_dir = args.cases_dir or config.get("telemac2d", {}).get("cases_dir", "cases")
    prepared = prepare_regions(config, grid, hotspots_path, cases_dir)
    for _, pc in prepared:
        print(f"[telemac] prepared case: {pc.case_dir}")
    return prepared


def cmd_prepare(args, config):
    _prepare(args, config)


def cmd_run(args, config):
    docker = (
        bool(config.get("telemac2d", {}).get("docker", True)) and not args.no_docker
    )
    if args.case:
        run_case(args.case, docker=docker, dry_run=args.dry_run)
    else:
        cases_dir = args.cases_dir or config.get("telemac2d", {}).get(
            "cases_dir", "cases"
        )
        run_all(cases_dir, docker=docker, dry_run=args.dry_run)


def cmd_postprocess(args, config):
    out_dir = args.output_dir or config["output"]["dir"]
    summary = postprocess_case(
        args.case_dir, config, out_dir, region_id=os.path.basename(args.case_dir)
    )
    print(json.dumps(summary, indent=2))


def cmd_pipeline(args, config):
    prepared = _prepare(args, config)
    docker = bool(config.get("telemac2d", {}).get("docker", True))
    out_dir = os.environ.get("OUTPUT_DIR") or config["output"]["dir"]
    for region, pc in prepared:
        run_case(pc.case_dir, docker=docker, dry_run=args.dry_run)
        region_out = os.path.join(out_dir, "telemac", region.id)
        postprocess_case(pc.case_dir, config, region_out, region_id=region.id)
        print(f"[telemac] post-processed -> {region_out}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="model.telemac", description="TELEMAC-2D refinement backend"
    )
    parser.add_argument("--config", "-c", default=None, help="Path to config YAML")
    sub = parser.add_subparsers(dest="command", required=True)

    p_prep = sub.add_parser("prepare", help="cluster hotspots and write cases")
    p_prep.add_argument("--hotspots", default=None, help="screening hotspots GeoJSON")
    p_prep.add_argument("--cases-dir", default=None)
    p_prep.set_defaults(func=cmd_prepare)

    p_run = sub.add_parser("run", help="run prepared case(s)")
    p_run.add_argument("--case", default=None, help="single case directory")
    p_run.add_argument("--cases-dir", default=None)
    p_run.add_argument(
        "--no-docker", action="store_true", help="use native telemac2d.py (no Docker)"
    )
    p_run.add_argument("--dry-run", action="store_true")
    p_run.set_defaults(func=cmd_run)

    p_pp = sub.add_parser("postprocess", help="convert .slf to canonical outputs")
    p_pp.add_argument("--case-dir", required=True)
    p_pp.add_argument("--output-dir", default=None)
    p_pp.set_defaults(func=cmd_postprocess)

    p_pipe = sub.add_parser("pipeline", help="prepare + run + postprocess")
    p_pipe.add_argument("--hotspots", default=None)
    p_pipe.add_argument("--cases-dir", default=None)
    p_pipe.add_argument("--dry-run", action="store_true")
    p_pipe.set_defaults(func=cmd_pipeline)

    return parser


def main():
    args = build_parser().parse_args()
    config = load_config(args.config)
    if os.environ.get("OUTPUT_DIR"):
        config.setdefault("output", {})["dir"] = os.environ["OUTPUT_DIR"]
    args.func(args, config)


if __name__ == "__main__":
    main()
