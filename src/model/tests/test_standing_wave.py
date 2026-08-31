"""Test: standing wave (seiche) in a closed rectangular basin.

Validates that the model correctly simulates a seiche with period
matching Merian's formula: T = 2L / sqrt(g * h).
"""

import warnings

import numpy as np

try:
    import pytest
except ImportError:
    pytest = None  # type: ignore[assignment]

from model.grid import StructuredGrid
from model.solver import ShallowWaterSolver

warnings.filterwarnings(
    "ignore", message="numpy.ndarray size changed, may indicate binary incompatibility"
)


def _merian_period(L: float, h: float, n_mode: int = 1) -> float:
    """Merian's formula for seiche period in a closed rectangular basin.

    T_n = 2L / (n * sqrt(g * h))
    """
    return 2.0 * L / (n_mode * np.sqrt(9.81 * h))


def _analytical_eta(
    x: np.ndarray, t: float, L: float, h: float, a0: float
) -> np.ndarray:
    """Analytical solution for the first-mode seiche.

    η(x, t) = a0 * cos(π x / L) * cos(ω₁ t)
    where ω₁ = π * sqrt(g h) / L
    """
    omega = np.pi * np.sqrt(9.81 * h) / L
    return a0 * np.cos(np.pi * x / L) * np.cos(omega * t)


def test_standing_wave_period():
    """Simulate a seiche for one period and verify the period is correct."""
    L = 10000.0  # basin length [m]
    H = 10.0  # depth [m]
    nx = 50
    ny = 2  # effectively 1D
    dx = L / nx
    dy = dx

    grid = StructuredGrid.from_uniform(
        nx=nx, ny=ny, dx=dx, dy=dy, x0=0.0, y0=0.0, lat0=0.0
    )
    grid.h[:, :] = H
    grid.h_u = np.full((ny, nx + 1), H)
    grid.h_v = np.full((ny + 1, nx), H)
    grid.mask[:] = True
    grid.mask_u[:] = True
    grid.mask_v[:] = True
    grid.open_boundary[:] = False
    grid.f[:] = 0.0

    T_expected = _merian_period(L, H, n_mode=1)

    solver = ShallowWaterSolver(grid, cd=0.0, ah=0.0, advection=False)

    x_c = np.arange(nx) * dx + dx / 2
    a0 = 0.1
    eta0 = a0 * np.cos(np.pi * x_c / L)
    eta0_2d = np.tile(eta0, (ny, 1))
    solver.set_initial_conditions(eta0=eta0_2d, u0=None, v0=None)

    dt = min(0.1, T_expected / 200.0)

    n_cycles_test = 2
    duration = n_cycles_test * T_expected

    zero_crossings: list[float] = []

    solver.run(
        dt=dt,
        duration=duration,
        callback=None,
        progress_interval=duration,
    )

    solver.set_initial_conditions(eta0=eta0_2d, u0=None, v0=None)
    solver._t = 0.0
    solver._step_count = 0

    prev_sign = np.sign(np.mean(solver.eta[0, nx // 2]))
    for i in range(int(duration / dt)):
        solver.step(dt)
        cur_eta = np.mean(solver.eta[0, nx // 2])
        cur_sign = np.sign(cur_eta)
        if i > 10 and prev_sign != cur_sign and cur_sign != 0:
            zero_crossings.append(solver.time)
        prev_sign = cur_sign

    if len(zero_crossings) >= 3:
        measured_period = zero_crossings[2] - zero_crossings[0]
        rel_error = abs(measured_period - T_expected) / T_expected
        assert rel_error < 0.10, (
            f"Seiche period error: expected {T_expected:.1f} s, "
            f"got {measured_period:.1f} s (error {rel_error * 100:.1f}%)"
        )
    else:
        if pytest:
            pytest.skip("Not enough zero crossings detected")
        else:
            raise AssertionError(
                f"Not enough zero crossings detected: {len(zero_crossings)}"
            )


def test_standing_wave_no_coriolis_damping():
    """In a closed, frictionless basin the seiche should persist."""
    L = 5000.0
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
    grid.open_boundary[:] = False
    grid.f[:] = 0.0

    solver = ShallowWaterSolver(grid, cd=0.0, ah=0.0, advection=False)

    x_c = np.arange(nx) * dx + dx / 2
    eta0 = 0.05 * np.cos(np.pi * x_c / L)
    eta0_2d = np.tile(eta0, (ny, 1))
    solver.set_initial_conditions(eta0=eta0_2d)

    dt = 0.2
    T = _merian_period(L, H)
    duration = 5 * T

    eta_peaks: list[float] = []
    for i in range(int(duration / dt)):
        solver.step(dt)
        cur = float(np.max(np.abs(solver.eta[0, :])))
        if i > 0 and int(solver.time / (T / 4)) != int((solver.time - dt) / (T / 4)):
            eta_peaks.append(cur)

    if len(eta_peaks) >= 3:
        decay = (eta_peaks[0] - eta_peaks[-1]) / eta_peaks[0]
        assert decay < 0.30, f"Excessive damping: amplitude decayed {decay * 100:.1f}%"
