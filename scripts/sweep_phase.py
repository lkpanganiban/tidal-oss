"""Sweep the imposed tidal phase speed to find a progressive (through-flow)
regime for the Surigao Strait box.  Reuses the already-built mesh/cli and only
regenerates the liquid-boundary .liq file for each candidate.
"""
import json
import shutil
import numpy as np
from model.telemac.selafin import read_geometry, read_serafin
from model.telemac.mesh import RefinementMesh
from model.telemac.boundaries import generate_boundaries
from model.telemac.runner import run_case
from model.telemac.postprocess import postprocess_case
from model.config import load_config

CASE = "cases_strait/region-001"
MANIFEST = f"{CASE}/mesh_manifest.json"
BASE_CFG = "scripts/telemac_strait_config.yaml"

mm = json.load(open(MANIFEST))
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
mesh_cfg = cfg["telemac2d"]["mesh"]

for ps in [0.7, 1.5, 2.2, 4.0, 8.0]:
    mesh_cfg["boundary"]["phase_speed_mps"] = ps
    generate_boundaries(
        mesh, mesh_cfg, tidal,
        np.arange(0, 2 * 86400 + 30, 30.0),
        CASE,
        edge_types=mesh_cfg["boundary"]["edge_types"],
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
    bands = [spd[idx == b].mean() for b in range(1, 9) if (idx == b).any()]
    print(f"ps={ps:4.1f}  min_band={min(bands):.4f}  max_band={max(bands):.4f}  "
          f"all_mean={spd.mean():.4f}  max_node={spd.max():.4f}")
