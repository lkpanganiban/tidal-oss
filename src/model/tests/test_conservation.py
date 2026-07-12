"""Test: mass and energy conservation in the solver."""

import warnings
warnings.filterwarnings(
    "ignore", message="numpy.ndarray size changed, may indicate binary incompatibility"
)

import numpy as np

try:
    import pytest
except ImportError:
    pytest = None  # type: ignore[assignment]

from model.grid import StructuredGrid
from model.solver import ShallowWaterSolver


def test_mass_conservation_closed_basin():
    """In a closed basin with zero normal flow, total volume must be conserved."""
    nx = 30
    ny = 20
    dx = 1000.0
    dy = 1000.0

    grid = StructuredGrid.from_uniform(
        nx=nx, ny=ny, dx=dx, dy=dy, lat0=0.0
    )

    depth = 50.0
    grid.h[:, :] = depth
    grid.h_u[:] = depth
    grid.h_v[:] = depth
    grid.mask[:] = True
    grid.mask_u[:] = True
    grid.mask_v[:] = True
    grid.open_boundary[:] = False
    grid.f[:] = 0.0

    x_c = np.arange(nx) * dx + dx / 2
    y_c = np.arange(ny) * dy + dy / 2
    yy, xx = np.meshgrid(y_c, x_c, indexing="ij")

    cx, cy = (nx - 1) * dx / 2, (ny - 1) * dy / 2
    sigma = 5000.0
    eta0 = 0.5 * np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * sigma**2))

    solver = ShallowWaterSolver(grid, cd=0.0, ah=0.0, advection=False)
    solver.set_initial_conditions(eta0=eta0, u0=None, v0=None)

    vol0 = solver.total_volume()

    dt = 1.0
    T_wave = 2.0 * 10000.0 / np.sqrt(9.81 * depth)

    solver.run(
        dt=dt,
        duration=2 * T_wave,
        callback=None,
        progress_interval=2 * T_wave,
    )

    vol1 = solver.total_volume()

    rel_diff = abs(vol1 - vol0) / vol0
    assert rel_diff < 0.01, (
        f"Mass conservation violated: initial={vol0:.3e}, final={vol1:.3e}, "
        f"diff={rel_diff*100:.4f}%"
    )


def test_mass_conservation_with_friction():
    """Friction should not cause spurious mass sources/sinks."""
    nx = 20
    ny = 15
    dx = 500.0
    dy = 500.0

    grid = StructuredGrid.from_uniform(
        nx=nx, ny=ny, dx=dx, dy=dy, lat0=0.0
    )
    grid.h[:, :] = 40.0
    grid.h_u[:] = 40.0
    grid.h_v[:] = 40.0
    grid.mask[:] = True
    grid.mask_u[:] = True
    grid.mask_v[:] = True
    grid.open_boundary[:] = False
    grid.f[:] = 0.0

    x_c = np.arange(nx) * dx + dx / 2
    eta0_1d = 0.3 * np.sin(2 * np.pi * x_c / (nx * dx))
    eta0 = np.tile(eta0_1d, (ny, 1))

    solver = ShallowWaterSolver(grid, cd=0.005, ah=0.0, advection=False)
    solver.set_initial_conditions(eta0=eta0, u0=None, v0=None)

    vol0 = solver.total_volume()

    dt = 0.5
    solver.run(
        dt=dt,
        duration=3600.0,
        callback=None,
        progress_interval=3600.0,
    )

    vol1 = solver.total_volume()

    rel_diff = abs(vol1 - vol0) / vol0
    assert rel_diff < 0.01, (
        f"Mass drift with friction: {rel_diff*100:.4f}%"
    )


def test_power_density_nonnegative():
    """Power density must be non-negative everywhere."""
    nx = 10
    ny = 8
    dx = 1000.0
    dy = 1000.0

    grid = StructuredGrid.from_uniform(
        nx=nx, ny=ny, dx=dx, dy=dy, lat0=0.0
    )
    grid.h[:, :] = 30.0
    grid.h_u[:] = 30.0
    grid.h_v[:] = 30.0
    grid.mask[:] = True
    grid.mask_u[:] = True
    grid.mask_v[:] = True
    grid.f[:] = 0.0

    solver = ShallowWaterSolver(grid, cd=0.0025, ah=0.0, advection=False)

    solver.u[:] = 1.0
    solver.v[:] = 0.5

    pd = solver.compute_power_density()
    assert np.all(pd >= 0.0), "Power density has negative values"
    assert np.any(pd > 0.0), "Power density is all zero for nonzero flow"
