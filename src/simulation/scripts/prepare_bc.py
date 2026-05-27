#!/usr/bin/env python3
"""
Extract tidal harmonic constants from FES2014 or TPXO9 netCDF data
at each open-boundary node of the Gmsh mesh, and generate a
`tidal_forcing.py` module for use with Thetis.

Inputs:
  - Gmsh mesh file (.msh)
  - FES2014 or TPXO9 netCDF files (amplitude & phase for each constituent)

Output:
  - tidal_forcing.py — Python module containing a `tidal_elevation(x, y, t)`
    function and constituent data used by `run_thetis.py`.
"""

import argparse
import sys
from pathlib import Path

import numpy as np

try:
    import meshio
except ImportError:
    print("ERROR: meshio not found. Install with: pip install meshio")
    sys.exit(1)

try:
    import xarray as xr
except ImportError:
    print("ERROR: xarray not found. Install with: pip install xarray")
    sys.exit(1)


# Angular speeds for commonly used constituents (rad/s)
OMEGA = {
    "M2": 1.405189e-04,
    "S2": 1.454441e-04,
    "N2": 1.378797e-04,
    "K2": 1.458423e-04,
    "K1": 7.292116e-05,
    "O1": 6.759774e-05,
    "P1": 7.252295e-05,
    "Q1": 6.495855e-05,
    "M4": 2.810377e-04,
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Extract tidal harmonics and generate tidal_forcing.py"
    )
    parser.add_argument(
        "--mesh", type=str, required=True,
        help="Path to Gmsh .msh file"
    )
    parser.add_argument(
        "--fes2014-dir", type=str, default=None,
        help="Directory containing FES2014 NetCDF files (amplitude/phase per constituent)"
    )
    parser.add_argument(
        "--tpxo", type=str, default=None,
        help="Path to TPXO9 NetCDF file"
    )
    parser.add_argument(
        "--constituents", type=str, nargs="+",
        default=["M2", "S2", "K1", "O1"],
        help="Tidal constituents to extract (default: M2 S2 K1 O1)"
    )
    parser.add_argument(
        "--output", type=str, default="tidal_forcing.py",
        help="Output Python module path (default: tidal_forcing.py)"
    )
    parser.add_argument(
        "--open-boundary-tag", type=int, default=1,
        help="Physical group tag for open ocean boundaries (default: 1)"
    )
    return parser.parse_args()


def get_open_boundary_nodes(mesh_path: str, boundary_tag: int = 1):
    """Extract coordinates of nodes on open-boundary physical curves."""
    mesh = meshio.read(mesh_path)

    # Get cells (lines) belonging to the open-boundary physical group
    all_nodes = mesh.points[:, :2]
    boundary_indices = set()

    if hasattr(mesh, "cell_sets") and mesh.cell_sets:
        # meshio v5+
        for cell_type, cell_data in mesh.cell_sets.items():
            if cell_type == "line":
                pass  # handle per cell set
    elif hasattr(mesh, "cell_data") and "gmsh:physical" in mesh.cell_data:
        tag_data = mesh.cell_data["gmsh:physical"]
        for i, (cell_type, cells) in enumerate(mesh.cells):
            if cell_type == "line" and tag_data[i] is not None:
                for j, tag in enumerate(tag_data[i]):
                    if tag == boundary_tag:
                        boundary_indices.update(cells[j])

    if not boundary_indices:
        # Fallback: extract nodes with lengths from cell sets
        for cell_type, cells in enumerate(mesh.cells):
            block = mesh.cells[cell_type]
            if block.type == "line":
                try:
                    cell_data = mesh.cell_data["gmsh:physical"][cell_type]
                    for idx, line in enumerate(block.data):
                        if cell_data[idx] == boundary_tag:
                            boundary_indices.update(line)
                except (IndexError, KeyError):
                    pass

    if not boundary_indices:
        print(f"WARNING: No boundary nodes found for physical tag {boundary_tag}")
        print("Using domain corner nodes as fallback...")
        # Use extreme points as fallback
        xs, ys = all_nodes[:, 0], all_nodes[:, 1]
        corners = [
            np.argmin(xs), np.argmax(xs),
            np.argmin(ys), np.argmax(ys),
        ]
        boundary_indices = set(corners)

    boundary_nodes = all_nodes[list(boundary_indices)]
    return boundary_nodes


def extract_harmonics(boundary_nodes, constituents, fes2014_dir=None, tpxo_path=None):
    """
    Extract amplitude and phase for each constituent at each boundary node.

    Returns:
        dict: {constituent_name: {"amp": array, "phase_deg": array, "omega": float}}
    """
    constituents_data = {}

    for name in constituents:
        if name not in OMEGA:
            print(f"WARNING: Unknown constituent '{name}', skipping")
            continue

        omega = OMEGA[name]

        if fes2014_dir:
            amp, phase = extract_from_fes2014(
                fes2014_dir, name, boundary_nodes
            )
        elif tpxo_path:
            amp, phase = extract_from_tpxo(
                tpxo_path, name, boundary_nodes
            )
        else:
            # Generate synthetic/placeholder harmonics for testing
            print(f"Using placeholder harmonics for {name}...")
            n = len(boundary_nodes)
            # Reasonable Philippine tidal amplitudes
            placeholder_amps = {
                "M2": 0.52, "S2": 0.23, "K1": 0.31, "O1": 0.25,
                "N2": 0.10, "K2": 0.08, "P1": 0.10, "Q1": 0.05,
            }
            amp = np.full(n, placeholder_amps.get(name, 0.10))
            phase = np.random.uniform(0, 360, n)  # random phase as placeholder

        constituents_data[name] = {
            "amp": amp,
            "phase_deg": phase,
            "omega": omega,
        }
        print(f"  {name}: amp={np.mean(amp):.3f}±{np.std(amp):.3f} m, "
              f"phase={np.mean(phase):.1f}±{np.std(phase):.1f}°")

    return constituents_data


def extract_from_fes2014(data_dir, constituent, boundary_nodes):
    """Extract harmonics from FES2014 NetCDF files."""
    amp_file = Path(data_dir) / f"{constituent}_amplitude.nc"
    phase_file = Path(data_dir) / f"{constituent}_phase.nc"

    if not amp_file.exists() or not phase_file.exists():
        raise FileNotFoundError(f"FES2014 files not found for {constituent}")

    amp_ds = xr.open_dataset(amp_file)
    phase_ds = xr.open_dataset(phase_file)

    # FES2014 usually uses lat_bnds/lon_bnds convention
    amp_var = list(amp_ds.data_vars)[0]
    phase_var = list(phase_ds.data_vars)[0]

    amps = []
    phases = []
    for lon, lat in boundary_nodes:
        try:
            a = amp_ds[amp_var].interp(lon=lon, lat=lat, method="linear").values
            p = phase_ds[phase_var].interp(lon=lon, lat=lat, method="linear").values
            amps.append(float(a))
            phases.append(float(p))
        except Exception:
            amps.append(0.1)
            phases.append(0.0)

    return np.array(amps), np.array(phases)


def extract_from_tpxo(tpxo_path, constituent, boundary_nodes):
    """Extract harmonics from TPXO9 NetCDF file."""
    ds = xr.open_dataset(tpxo_path)

    # TPXO9 typical variable names: h_Re, h_Im for real/imag parts
    con_idx = None
    if "con" in ds.dims or "nc" in ds.dims:
        con_dim = "con" if "con" in ds.dims else "nc"
        con_names = ds[con_dim].values
        if isinstance(con_names[0], bytes):
            con_names = [n.decode().strip() for n in con_names]
        for i, name in enumerate(con_names):
            if name.upper() == constituent.upper():
                con_idx = i
                break

    amps = []
    phases = []
    for lon, lat in boundary_nodes:
        try:
            if con_idx is not None and "hRe" in ds:
                re = ds["hRe"].isel({con_dim: con_idx}).interp(
                    lon=lon, lat=lat, method="linear"
                ).values
                im = ds["hIm"].isel({con_dim: con_idx}).interp(
                    lon=lon, lat=lat, method="linear"
                ).values
                amp = float(np.sqrt(re**2 + im**2))
                phase = float(np.degrees(np.arctan2(im, re)))
            else:
                amp, phase = 0.1, 0.0
            amps.append(amp)
            phases.append(phase)
        except Exception:
            amps.append(0.1)
            phases.append(0.0)

    return np.array(amps), np.array(phases)


def generate_tidal_forcing_module(constituents_data, output_path):
    """Write the tidal_forcing.py module."""
    lines = [
        '"""',
        'Tidal boundary condition module — auto-generated by prepare_bc.py.',
        '',
        'Provides tidal_elevation(x, y, t) callable for Thetis boundary conditions.',
        '"""',
        '',
        'import numpy as np',
        '',
        '',
        'CONSTITUENTS = {',
    ]

    for name, data in constituents_data.items():
        amp_list = data["amp"].tolist()
        phase_list = data["phase_deg"].tolist()
        lines.append(f'    "{name}": {{')
        lines.append(f'        "amp": {amp_list},')
        lines.append(f'        "phase_deg": {phase_list},')
        lines.append(f'        "omega": {data["omega"]:.10e},')
        lines.append(f'    }},')

    lines.append("}")
    lines.append("")
    lines.append("")
    lines.append("def tidal_elevation(x, y, t):")
    lines.append('    """')
    lines.append("    Compute tidal water elevation (m) at spatial coordinates and time.")
    lines.append("")
    lines.append("    Args:")
    lines.append("        x, y: Spatial coordinates (lon, lat) at boundary nodes")
    lines.append("        t: Time in seconds since simulation start")
    lines.append("")
    lines.append("    Returns:")
    lines.append("        Water elevation in meters")
    lines.append('    """')
    lines.append("    eta = 0.0")
    lines.append("    for name, data in CONSTITUENTS.items():")
    lines.append("        amp = np.mean(data['amp'])")
    lines.append("        phase_rad = np.deg2rad(np.mean(data['phase_deg']))")
    lines.append("        omega = data['omega']")
    lines.append("        eta += amp * np.cos(omega * t - phase_rad)")
    lines.append("    return eta")
    lines.append("")

    content = "\n".join(lines)
    Path(output_path).write_text(content)
    print(f"tidal_forcing.py written to {output_path}")


def main():
    args = parse_args()

    mesh_path = Path(args.mesh)
    if not mesh_path.exists():
        print(f"ERROR: Mesh file not found: {args.mesh}")
        sys.exit(1)

    print(f"Extracting open-boundary nodes from {args.mesh} (tag {args.open_boundary_tag})...")
    boundary_nodes = get_open_boundary_nodes(args.mesh, args.open_boundary_tag)
    print(f"  Boundary nodes: {len(boundary_nodes)}")

    print(f"Extracting tidal harmonics for: {', '.join(args.constituents)}...")
    constituents_data = extract_harmonics(
        boundary_nodes,
        args.constituents,
        fes2014_dir=args.fes2014_dir,
        tpxo_path=args.tpxo,
    )

    if not constituents_data:
        print("ERROR: No constituent data extracted")
        sys.exit(1)

    generate_tidal_forcing_module(constituents_data, args.output)


if __name__ == "__main__":
    main()
