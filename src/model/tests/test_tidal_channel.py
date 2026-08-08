"""Test: tidal channel forced by M2 at the open (left) boundary.

A 1D channel driven by a prescribed M2 elevation at the left boundary;
the right boundary is a closed wall.  Validates:
  - Correct velocity amplitude for a friction-dominated channel
  - Phase relationship between elevation and velocity
"""

import warnings

warnings.filterwarnings(
    "ignore", message="numpy.ndarray size changed, may indicate binary incompatibility"
)

import numpy as np

try:
    import pytest
except ImportError:
    pytest = None  # type: ignore[assignment]

from model.forcing import ASTRO_FREQUENCIES
from model.grid import StructuredGrid
from model.solver import ShallowWaterSolver


def test_tidal_channel_develops_flow():
    """An M2-forced channel should develop an oscillating flow."""
    L = 50000.0  # channel length [m]
    H = 30.0  # depth [m]
    nx = 60
    ny = 3
    dx = L / nx
    dy = dx

    grid = StructuredGrid.from_uniform(nx=nx, ny=ny, dx=dx, dy=dy, lat0=0.0)
    grid.h[:, :] = H
    grid.h_u[:] = H
    grid.h_v[:] = H
    grid.mask[:] = True
    grid.mask_u[:] = True
    grid.mask_v[:] = True
    grid.open_boundary[:] = False
    grid.open_boundary[:, 0] = True  # left boundary open (forced)
    grid.f[:] = 0.0

    amp = 0.5
    omega = ASTRO_FREQUENCIES["M2"]

    def eta_func(t: float) -> np.ndarray:
        bc = np.zeros((grid.ny, grid.nx))
        bc[grid.open_boundary] = amp * np.cos(omega * t)
        return bc

    solver = ShallowWaterSolver(grid, cd=0.0025, ah=0.0, advection=False)
    solver.set_open_boundary_eta(eta_func)

    T = 2 * np.pi / omega
    dt = 5.0

    solver.run(
        dt=dt,
        duration=3 * T,
        callback=None,
        progress_interval=3 * T,
    )

    u_mid = np.mean(np.abs(solver.u[1, nx // 2]))
    assert u_mid > 0.005, f"Flow too weak: |u| = {u_mid:.4f} m/s at channel midpoint"


def test_tidal_channel_phase():
    """Velocity should lead elevation by approximately 90° in a frictionless
    channel, and somewhat less in a frictional one."""
    L = 30000.0
    H = 20.0
    nx = 40
    ny = 3
    dx = L / nx
    dy = dx

    grid = StructuredGrid.from_uniform(nx=nx, ny=ny, dx=dx, dy=dy, lat0=0.0)
    grid.h[:, :] = H
    grid.h_u[:] = H
    grid.h_v[:] = H
    grid.mask[:] = True
    grid.mask_u[:] = True
    grid.mask_v[:] = True
    grid.open_boundary[:, 0] = True  # left boundary open (forced)
    grid.f[:] = 0.0

    amp = 0.3
    omega = ASTRO_FREQUENCIES["M2"]

    def eta_func(t: float) -> np.ndarray:
        bc = np.zeros((grid.ny, grid.nx))
        bc[grid.open_boundary] = amp * np.cos(omega * t)
        return bc

    solver = ShallowWaterSolver(grid, cd=0.001, ah=0.0, advection=False)
    solver.set_open_boundary_eta(eta_func)

    T = 2 * np.pi / omega
    dt = 3.0

    histories: dict[str, list] = {"t": [], "eta": [], "u": []}

    def callback(solv, step):
        histories["t"].append(solv.time)
        histories["eta"].append(solv.eta[1, nx // 2])
        histories["u"].append(solv.u[1, nx // 2])
        return None

    solver.run(
        dt=dt,
        duration=6 * T,
        callback=callback,
        progress_interval=6 * T,
    )

    t_arr = np.array(histories["t"])
    eta_arr = np.array(histories["eta"])
    u_arr = np.array(histories["u"])

    last_period = t_arr >= 5 * T
    t_period = t_arr[last_period]
    eta_p = eta_arr[last_period]
    u_p = u_arr[last_period]

    u_range = np.max(u_p) - np.min(u_p)
    assert u_range > 0.02, f"Velocity amplitude too small: {u_range:.4f} m/s"

    cross_corr = np.correlate(u_p - np.mean(u_p), eta_p - np.mean(eta_p), mode="same")
    peak_lag = np.argmax(cross_corr) - len(cross_corr) // 2
    dt_avg = np.mean(np.diff(t_period))
    phase_shift = peak_lag * omega * dt_avg

    assert -np.pi / 2 < phase_shift < np.pi, (
        f"Unexpected phase shift: {phase_shift:.2f} rad"
    )
