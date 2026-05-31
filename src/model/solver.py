"""2D depth-averaged shallow-water solver on an Arakawa C-grid.

Implements the forward-backward time-stepping scheme with semi-implicit
bottom friction.  Supports tidal open-boundary forcing, Coriolis,
wetting/drying, and optional advection / horizontal mixing terms.
"""

from __future__ import annotations

import logging
import time as time_module
from typing import Callable, Union

import numpy as np

from .grid import StructuredGrid
from .utils import (
    interpolate_to_u,
    interpolate_to_v,
    v_at_u_pts,
    u_at_v_pts,
    speed,
    power_density,
)

logger = logging.getLogger(__name__)

G = 9.81
RHO_SEAWATER = 1025.0
H_MIN = 0.05


class ShallowWaterSolver:
    """Forward-backward shallow-water solver on an Arakawa C-grid.

    The time-stepping scheme:
      1. Momentum tendency (pressure gradient, Coriolis, advection, mixing).
      2. Semi-implicit bottom-friction correction.
      3. Free-surface update via continuity.
      4. Boundary-condition enforcement.

    Open-boundary cells have η prescribed; u/v at open edges use zero-gradient.
    """

    def __init__(
        self,
        grid: StructuredGrid,
        cd: float = 0.0025,
        ah: float = 0.0,
        advection: bool = False,
        rho: float = RHO_SEAWATER,
        h_min: float = H_MIN,
    ):
        self.grid = grid
        self.cd = cd
        self.ah = ah
        self.advection = advection
        self.rho = rho
        self.h_min = h_min

        self.ny, self.nx = grid.shape
        self.dx = grid.dx
        self.dy = grid.dy

        self.eta = np.zeros((self.ny, self.nx), dtype=np.float64)
        self.u = np.zeros((self.ny, self.nx + 1), dtype=np.float64)
        self.v = np.zeros((self.ny + 1, self.nx), dtype=np.float64)

        self.f_u = interpolate_to_u(grid.f)
        self.f_v = interpolate_to_v(grid.f)

        self._t: float = 0.0
        self._step_count: int = 0
        self._eta_bc: Callable[[float], np.ndarray] | None = None
        self._tidal_bnd = None

    @property
    def time(self) -> float:
        return self._t

    def set_initial_conditions(
        self,
        eta0: np.ndarray | None = None,
        u0: np.ndarray | None = None,
        v0: np.ndarray | None = None,
    ):
        if eta0 is not None:
            self.eta[:] = eta0
        else:
            self.eta[:] = 0.0
        if u0 is not None:
            self.u[:] = u0
        else:
            self.u[:] = 0.0
        if v0 is not None:
            self.v[:] = v0
        else:
            self.v[:] = 0.0
        self._apply_masks()

    def set_open_boundary_eta(
        self, bc: Union["Callable[[float], np.ndarray]", object]
    ):
        """Register boundary forcing — either a callable f(t_seconds)->eta[ny,nx]
        or a :class:`TidalBoundary` object."""
        if callable(bc):
            self._eta_bc = bc
            self._tidal_bnd = None
        else:
            self._eta_bc = None
            self._tidal_bnd = bc

    def step(self, dt: float):
        """Advance one time step of size dt [s].

        Uses forward-backward: momentum first, then continuity.
        Bottom friction is treated semi-implicitly.
        """
        C_d = self.cd
        dx = self.dx
        dy = self.dy

        if self._eta_bc is not None or self._tidal_bnd is not None:
            self._apply_eta_bc()

        h_c = np.maximum(self.grid.h + self.eta, self.h_min)
        mask = self.grid.mask
        mask_u = self.grid.mask_u
        mask_v = self.grid.mask_v

        h_u = interpolate_to_u(h_c)
        h_v = interpolate_to_v(h_c)

        # ---- u-momentum ----
        dpdx = _pressure_gradient_x(self.eta, dx)
        v_interp = v_at_u_pts(self.v)
        u_speed = np.sqrt(self.u**2 + v_interp**2)
        inv_h_u = 1.0 / np.maximum(h_u, self.h_min)

        du_dt = -G * dpdx + self.f_u * v_interp
        du_dt -= C_d * self.u * u_speed * inv_h_u

        if self.ah > 0.0:
            du_dt += self._laplacian(self.u, dx, dy)
        if self.advection:
            du_dt += self._advection_u()

        friction_u = dt * C_d * u_speed * inv_h_u
        self.u[mask_u] = (self.u[mask_u] + dt * du_dt[mask_u]) / (
            1.0 + friction_u[mask_u]
        )
        self.u[~mask_u] = 0.0

        # ---- v-momentum ----
        dpdy = _pressure_gradient_y(self.eta, dy)
        u_interp = u_at_v_pts(self.u)
        v_speed = np.sqrt(u_interp**2 + self.v**2)
        inv_h_v = 1.0 / np.maximum(h_v, self.h_min)

        dv_dt = -G * dpdy - self.f_v * u_interp
        dv_dt -= C_d * self.v * v_speed * inv_h_v

        if self.ah > 0.0:
            dv_dt += self._laplacian(self.v, dx, dy)
        if self.advection:
            dv_dt += self._advection_v()

        friction_v = dt * C_d * v_speed * inv_h_v
        self.v[mask_v] = (self.v[mask_v] + dt * dv_dt[mask_v]) / (
            1.0 + friction_v[mask_v]
        )
        self.v[~mask_v] = 0.0

        self._apply_uv_open_bc()

        # ---- continuity (η update) ----
        flx_x = h_u[:, 1:] * self.u[:, 1:] - h_u[:, :-1] * self.u[:, :-1]
        flx_y = h_v[1:, :] * self.v[1:, :] - h_v[:-1, :] * self.v[:-1, :]

        interior = mask & (~self.grid.open_boundary)
        self.eta[interior] -= dt * (flx_x[interior] / dx + flx_y[interior] / dy)
        self.eta[~mask] = 0.0

        self._t += dt
        self._step_count += 1

    def run(
        self,
        dt: float,
        duration: float,
        callback: Callable | None = None,
        progress_interval: float = 3600.0,
    ) -> list[dict]:
        """Run for *duration* seconds with time step *dt*.

        Returns snapshots collected by the optional callback.
        """
        n_steps = int(np.ceil(duration / dt))
        dt_actual = duration / n_steps

        logger.info(
            "Starting simulation: %d steps x %.3f s = %.1f days",
            n_steps,
            dt_actual,
            duration / 86400.0,
        )

        snapshots: list[dict] = []
        t0_wall = time_module.monotonic()
        last_log = 0.0

        for step in range(n_steps):
            self.step(dt_actual)

            if callback is not None:
                snap = callback(self, step)
                if snap is not None:
                    snapshots.append(snap)

            if self._t - last_log >= progress_interval:
                elapsed = time_module.monotonic() - t0_wall
                pct = 100.0 * self._t / duration
                _active = self.grid.mask
                eta_max = float(np.max(np.abs(self.eta[_active]))) if _active.any() else 0.0
                spd = speed(self.u, self.v)
                u_max = float(np.max(spd[_active])) if _active.any() else 0.0
                logger.info(
                    "t=%.1f d (%5.1f%%) | wall=%.0f s | max|η|=%.2f m | max|U|=%.2f m/s",
                    self._t / 86400.0,
                    pct,
                    elapsed,
                    eta_max,
                    u_max,
                )
                last_log = self._t

        wall_time = time_module.monotonic() - t0_wall
        logger.info(
            "Simulation complete: %.1f d simulated in %.0f s wall time",
            duration / 86400.0,
            wall_time,
        )
        return snapshots

    def compute_power_density(self) -> np.ndarray:
        """Instantaneous power density [W/m²] from current state."""
        return power_density(self.u, self.v, rho=self.rho)

    def total_volume(self) -> float:
        """Total volume (for mass-conservation checks)."""
        h_c = np.maximum(self.grid.h + self.eta, 0.0)
        return float(np.sum(h_c[self.grid.mask] * self.dx * self.dy))

    # -- internal helpers ---------------------------------------------------

    def _apply_masks(self):
        self.eta[~self.grid.mask] = 0.0
        self.u[~self.grid.mask_u] = 0.0
        self.v[~self.grid.mask_v] = 0.0

    def _apply_eta_bc(self):
        ob = self.grid.open_boundary
        if self._eta_bc is not None:
            self.eta[ob] = self._eta_bc(self._t)[ob]
        elif self._tidal_bnd is not None:
            self.eta[ob] = self._tidal_bnd.evaluate_at(self._t)

    def _apply_uv_open_bc(self):
        zero_gradient = False
        if zero_gradient:
            ob_c = self.grid.open_boundary
            ny, nx = self.ny, self.nx
            for j in range(ny):
                if ob_c[j, 0]:
                    self.u[j, 0] = self.u[j, 1]
                if ob_c[j, nx - 1]:
                    self.u[j, nx] = self.u[j, nx - 1]
            for i in range(nx):
                if ob_c[0, i]:
                    self.v[0, i] = self.v[1, i]
                if ob_c[ny - 1, i]:
                    self.v[ny, i] = self.v[ny - 1, i]

    @staticmethod
    def _laplacian(phi: np.ndarray, dx: float, dy: float) -> np.ndarray:
        """Central-difference Laplacian at interior points."""
        lap = np.zeros_like(phi)
        interior_slc = tuple(
            slice(1, s - 1) if s > 2 else slice(0, 0) for s in phi.shape
        )
        if phi.ndim == 2:
            j_slc, i_slc = interior_slc
            lap[j_slc, i_slc] = (
                phi[j_slc, i_slc + 1]
                + phi[j_slc, i_slc - 1]
                - 2.0 * phi[j_slc, i_slc]
            ) / dx**2 + (
                phi[j_slc + 1, i_slc]
                + phi[j_slc - 1, i_slc]
                - 2.0 * phi[j_slc, i_slc]
            ) / dy**2
        return lap

    def _advection_u(self) -> np.ndarray:
        """Advection at u-points: -(u du/dx + v du/dy)."""
        adv = np.zeros_like(self.u)
        ny, nx1 = self.u.shape
        nx = nx1 - 1

        u_c = 0.5 * (self.u[:, :-1] + self.u[:, 1:])

        dudx = np.zeros_like(self.u)
        if nx >= 2:
            dudx[:, 1:nx] = (u_c[:, 1:] - u_c[:, :-1]) / self.dx

        v_at_u = v_at_u_pts(self.v)

        dudy = np.zeros_like(self.u)
        if ny >= 3:
            dudy[1 : ny - 1, :] = (
                self.u[2:ny, :] - self.u[: ny - 2, :]
            ) / (2.0 * self.dy)

        adv = -(self.u * dudx + v_at_u * dudy)
        return adv

    def _advection_v(self) -> np.ndarray:
        """Advection at v-points: -(u dv/dx + v dv/dy)."""
        adv = np.zeros_like(self.v)
        ny1, nx = self.v.shape
        ny = ny1 - 1

        v_c = 0.5 * (self.v[:-1, :] + self.v[1:, :])

        dvdy = np.zeros_like(self.v)
        if ny >= 2:
            dvdy[1:ny, :] = (v_c[1:, :] - v_c[:-1, :]) / self.dy

        u_at_v = u_at_v_pts(self.u)

        dvdx = np.zeros_like(self.v)
        if nx >= 3:
            dvdx[:, 1 : nx - 1] = (
                self.v[:, 2:nx] - self.v[:, : nx - 2]
            ) / (2.0 * self.dx)

        adv = -(u_at_v * dvdx + self.v * dvdy)
        return adv


def _pressure_gradient_x(eta: np.ndarray, dx: float) -> np.ndarray:
    """Pressure gradient at u-points: (η_right - η_left) / dx.

    eta: (ny, nx) -> dpdx: (ny, nx+1) at u-points.
    """
    ny, nx = eta.shape
    dpdx = np.zeros((ny, nx + 1), dtype=eta.dtype)
    dpdx[:, 1:nx] = (eta[:, 1:] - eta[:, :-1]) / dx
    dpdx[:, 0] = (eta[:, 0] - eta[:, 0]) / dx
    dpdx[:, nx] = (eta[:, nx - 1] - eta[:, nx - 1]) / dx
    return dpdx


def _pressure_gradient_y(eta: np.ndarray, dy: float) -> np.ndarray:
    """Pressure gradient at v-points: (η_upper - η_lower) / dy.

    eta: (ny, nx) -> dpdy: (ny+1, nx) at v-points.
    """
    ny, nx = eta.shape
    dpdy = np.zeros((ny + 1, nx), dtype=eta.dtype)
    dpdy[1:ny, :] = (eta[1:, :] - eta[:-1, :]) / dy
    dpdy[0, :] = (eta[0, :] - eta[0, :]) / dy
    dpdy[ny, :] = (eta[ny - 1, :] - eta[ny - 1, :]) / dy
    return dpdy
