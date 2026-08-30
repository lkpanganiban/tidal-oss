"""Sweep the imposed tidal phase speed to find a progressive (through-flow)
regime for the Surigao Strait box.  Reuses the already-built mesh/cli and only
regenerates the liquid-boundary .liq file for each candidate.

The case steering file is also rewritten for the sweep window (2 days at the
case time step) so TELEMAC never queries the liquid-boundary file past its
coverage.
"""

import json
import os
import shutil
import sys

import numpy as np

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")
)

from model.config import load_config
from model.telemac.boundaries import generate_boundaries
from model.telemac.mesh import RefinementMesh
from model.telemac.postprocess import postprocess_case
from model.telemac.runner import run_case
from model.telemac.selafin import read_geometry, read_serafin
from model.telemac.steering import build_steering

CASE = "cases/region-001"
MANIFEST = f"{CASE}/mesh_manifest.json"
BASE_CFG = "scripts/telemac_strait_config.yaml"

TIME_STEP = 30.0
DURATION_DAYS = 2
WINDOW_S = DURATION_DAYS * 86400
SWEEP_TIMES = np.arange(0, WINDOW_S + TIME_STEP, TIME_STEP)
N_STEPS = int(round(WINDOW_S / TIME_STEP))

with open(MANIFEST) as f:
    mm = json.load(f)
geom = read_geometry(f"{CASE}/mesh.slf")
mesh = RefinementMesh(
    path=f"{CASE}/mesh.slf",
    geometry=geom,
    lon0=mm["lon0"],
    lat0=mm["lat0"],
    node_lon=np.array(mm["node_lon"]),
    node_lat=np.array(mm["node_lat"]),
    coordinates_are_meters=True,
    bbox=mm["bbox"],
    liquid_ipobo=None,  # fall back to edge_types classification
)

cfg = load_config(BASE_CFG)
tidal = cfg.get("tidal_forcing", {})
telemac_cfg = cfg["telemac2d"]
mesh_cfg = telemac_cfg["mesh"]

# Rewrite the steering file to the sweep window so case.cas matches the 2-day
# .liq coverage (the prepared case may use the default 15-day duration).
build_steering(
    CASE,
    TIME_STEP,
    N_STEPS,
    telemac_cfg,
    title="TIDAL-OSS SWEEP",
    save_interval_hours=1.0,
)

for ps in [0.7, 1.5, 2.2, 4.0, 8.0]:
    mesh_cfg["boundary"]["phase_speed_mps"] = ps
    generate_boundaries(
        mesh,
        mesh_cfg,
        tidal,
        SWEEP_TIMES,
        CASE,
        edge_types=mesh_cfg["boundary"]["edge_types"],
        propagation_axis=mesh_cfg["boundary"].get("propagation_axis", "lat"),
    )
    out = f"output/telemac/sweep_{ps}"
    shutil.rmtree(out, ignore_errors=True)
    run_case(CASE, docker=True)
    postprocess_case(CASE, cfg, out, region_id=f"sweep_{ps}")
    res = read_serafin(f"{CASE}/r2d.slf")
    u = res["variables"]["VELOCITY U"]
    v = res["variables"]["VELOCITY V"]
    spd = np.sqrt(u**2 + v**2).mean(axis=0)
    # group by latitude band
    lat = mesh.node_lat
    bins = np.linspace(lat.min(), lat.max(), 9)
    idx = np.digitize(lat, bins)
    bands = [spd[idx == b].mean() for b in range(1, bins.size + 1) if (idx == b).any()]
    if not bands:
        print(f"ps={ps:4.1f}  no nodes in any latitude band")
        continue
    print(
        f"ps={ps:4.1f}  min_band={min(bands):.4f}  max_band={max(bands):.4f}  "
        f"all_mean={spd.mean():.4f}  max_node={spd.max():.4f}"
    )
