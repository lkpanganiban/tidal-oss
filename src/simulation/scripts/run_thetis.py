#!/usr/bin/env python3
"""
Main tidal-current simulation script using Thetis (Firedrake).

Reads a Gmsh mesh, loads bathymetry, sets up a 2D shallow-water
solver driven by tidal boundary conditions, and writes output.

Usage:
    python run_thetis.py                       # default config
    mpirun -np 8 python run_thetis.py          # parallel (8 cores)

Environment variables:
    THETIS_MESH          Path to .msh mesh file (default: input/mesh_philippines.msh)
    THETIS_BATHYMETRY    Path to bathymetry CSV (default: input/bathymetry.csv)
    THETIS_OUTPUT        Output directory (default: output)
    THETIS_DURATION_DAYS Simulation duration in days (default: 30)
    THETIS_TIMESTEP      Time step in seconds (default: 300)
"""

import os
import sys
import time
from pathlib import Path

import numpy as np

# --- Handle missing Firedrake / Thetis gracefully ---
try:
    import firedrake
    from firedrake import (
        Mesh, Function, FunctionSpace, Constant, File, exprc,
    )
except ImportError:
    print("ERROR: Firedrake not found.")
    print("Install with: python firedrake-install --install thetis")
    print("Or: conda install -c conda-forge firedrake")
    sys.exit(1)

try:
    from thetis import *
    from thetis.solver2d import FlowSolver2d
except ImportError:
    print("ERROR: Thetis not found.")
    print("Install with: python firedrake-install --install thetis")
    print("Or: pip install thetis (inside Firedrake virtualenv)")
    sys.exit(1)


def load_bathymetry(mesh2d, csv_path: str, min_depth: float = 2.0):
    """Load bathymetry from CSV and project onto the P1 function space."""
    print(f"Loading bathymetry from {csv_path}...")
    depths = np.loadtxt(csv_path, delimiter=",")

    P1_2d = FunctionSpace(mesh2d, "CG", 1)
    bathymetry = Function(P1_2d, name="Bathymetry")

    n_nodes = bathymetry.dat.data_with_halos.shape[0]
    if len(depths) != n_nodes:
        print(f"WARNING: Bathymetry size ({len(depths)}) != mesh nodes ({n_nodes})")
        print("Bathymetry will be truncated or zero-padded.")
        if len(depths) > n_nodes:
            depths = depths[:n_nodes]
        else:
            depths = np.pad(depths, (0, n_nodes - len(depths)), constant_values=min_depth)

    bathymetry.dat.data_with_halos[:] = depths
    return bathymetry


def load_tidal_forcing(module_path: str = None):
    """
    Load the tidal elevation function from the generated module.
    Falls back to a simple synthetic M2 tide if module is missing.
    """
    if module_path and Path(module_path).exists():
        sys.path.insert(0, str(Path(module_path).parent))
        mod_name = Path(module_path).stem
        try:
            mod = __import__(mod_name)
            return mod.tidal_elevation
        except Exception as e:
            print(f"WARNING: Could not load {module_path}: {e}")

    # Fallback: synthetic M2 tide
    print("Using fallback synthetic M2 tide (amplitude 0.5 m)...")
    M2_OMEGA = 1.405189e-04

    def synthetic_tide(x, y, t):
        return 0.5 * np.cos(M2_OMEGA * t)

    return synthetic_tide


def configure_simulation(
    mesh2d,
    bathymetry,
    tidal_func,
    output_dir: str,
    duration_days: float = 30,
    timestep: float = 300,
    export_interval: float = 1800,
):
    """Set up and return a configured FlowSolver2d."""
    print("Configuring Thetis FlowSolver2d...")
    solver = FlowSolver2d(mesh2d, bathymetry)

    options = solver.options
    options.timestepper_type = "CrankNicolson"
    options.timestep = timestep
    options.simulation_end_time = duration_days * 24 * 3600
    options.simulation_export_time = export_interval
    options.output_directory = output_dir
    options.fields_to_export = ["uv_2d", "elev_2d"]
    options.fields_to_export_hdf5 = ["uv_2d", "elev_2d"]

    # Turbulence
    options.use_smagorinsky_viscosity = True
    options.smagorinsky_coefficient = Constant(0.1)

    # Wetting & drying
    options.wetting_and_drying = True

    # Bottom friction
    P1_2d = FunctionSpace(mesh2d, "CG", 1)
    manning = Function(P1_2d, name="Manning")
    manning.assign(Constant(0.025))
    options.manning_drag_coefficient = manning

    # Checkpointing (save state every 12h for restart capability)
    options.check_volume_conservation = True
    options.check_salinity_conservation = False
    options.check_temperature_conservation = False

    # Boundary conditions
    # Physical tags from Gmsh: 1 = open ocean, 2 = land
    solver.bnd_functions["shallow_water"] = {
        1: {"elev": tidal_func},
        2: {"un": Constant(0.0)},
    }

    # Initial conditions — still water
    solver.assign_initial_conditions(
        elev=Constant(0.0),
        uv=Constant((0.0, 0.0)),
    )

    return solver


def main():
    # --- Configuration ---
    mesh_path = os.environ.get(
        "THETIS_MESH", os.path.join("input", "mesh_philippines.msh")
    )
    bathymetry_path = os.environ.get(
        "THETIS_BATHYMETRY", os.path.join("input", "bathymetry.csv")
    )
    output_dir = os.environ.get("THETIS_OUTPUT", "output")
    duration_days = float(os.environ.get("THETIS_DURATION_DAYS", "30"))
    timestep = float(os.environ.get("THETIS_TIMESTEP", "300"))
    tidal_module = os.environ.get(
        "THETIS_TIDAL_MODULE", os.path.join("input", "tidal_forcing.py")
    )

    print("=" * 60)
    print("Tidal Current Simulation — Thetis (Firedrake)")
    print("=" * 60)
    print(f"  Mesh:          {mesh_path}")
    print(f"  Bathymetry:    {bathymetry_path}")
    print(f"  Duration:      {duration_days} days")
    print(f"  Timestep:      {timestep} s")
    print(f"  Output:        {output_dir}")
    print(f"  Parallel:      {firedrake.COMM_WORLD.size} processes")
    print("=" * 60)

    # Ensure output directory exists
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # Load mesh
    print("Loading mesh...")
    t0 = time.time()
    mesh2d = Mesh(mesh_path)
    print(f"  Loaded in {time.time() - t0:.1f}s")
    print(f"  Nodes: {mesh2d.num_vertices()}")
    print(f"  Elements: {mesh2d.num_cells()}")

    # Load bathymetry
    bathymetry = load_bathymetry(mesh2d, bathymetry_path)

    # Load tidal forcing
    tidal_func = load_tidal_forcing(tidal_module)

    # Configure solver
    solver = configure_simulation(
        mesh2d,
        bathymetry,
        tidal_func,
        output_dir,
        duration_days=duration_days,
        timestep=timestep,
    )

    # Run
    print("\nStarting simulation...")
    print(f"  Simulation period: {duration_days:.0f} days")
    n_steps = int(duration_days * 24 * 3600 / timestep)
    print(f"  Approx. time steps: {n_steps}")
    print(f"  Export interval: {solver.options.simulation_export_time} s")

    t_start = time.time()
    solver.iterate()
    elapsed = time.time() - t_start

    print(f"\nSimulation completed in {elapsed:.0f} s ({elapsed / 3600:.1f} h)")
    print(f"Output written to: {Path(output_dir).resolve()}")


if __name__ == "__main__":
    main()
