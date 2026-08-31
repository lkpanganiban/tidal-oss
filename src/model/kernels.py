"""Numba-JIT kernels for the shallow-water solver's hot time-stepping loop.

The default production path (no horizontal viscosity ``ah == 0`` and no
advection) is implemented as a single fused ``@njit`` kernel that mirrors
the vectorised NumPy implementation in :class:`ShallowWaterSolver.step`
arithmetic-for-arithmetic.  The NumPy path remains the fallback and is used
whenever ``ah > 0`` or ``advection`` is enabled.

The kernel updates ``eta``, ``u``, ``v`` **in place**.  It expects the open
boundary condition to have already been applied to ``eta`` (the solver does
this before calling the kernel).

Grid layout (Arakawa C-grid):
    eta : (ny, nx)      cell centres
    u   : (ny, nx + 1)  x-faces
    v   : (ny + 1, nx)  y-faces
"""

from __future__ import annotations

import numpy as np

try:  # numba is optional; the solver falls back to pure NumPy without it
    from numba import njit

    _NUMBA_AVAILABLE = True

except ImportError:  # pragma: no cover - exercised only on numba-less installs
    _NUMBA_AVAILABLE = False

    def njit(*args, **kwargs):  # type: ignore[no-redef,misc]
        """No-op decorator so the module imports cleanly without numba."""

        def _identity(fn):
            return fn

        return _identity


def numba_available() -> bool:
    """True if numba can be used for the fused kernel."""
    return _NUMBA_AVAILABLE


# Note: no ``cache=True`` — numba's on-disk cache stores the kernel's module
# name, so the same function imported as ``model.kernels`` (editable install /
# notebook) and as ``src.model.kernels`` (``python -m src.model.run``) would
# load each other's cache and fail to ``import src``.  In-memory JIT compiles
# once per process (~1 s) and is immune to the two import styles.
@njit(fastmath=False)
def _step_forward_backward(
    eta,
    u,
    v,
    h,
    f_u,
    f_v,
    mask,
    mask_u,
    mask_v,
    open_boundary,
    cd: float,
    g: float,
    dx: float,
    dy: float,
    dt: float,
    h_min: float,
):
    """One forward-backward time step (momentum then continuity).

    Mirrors ``ShallowWaterSolver.step`` with ``ah == 0`` and
    ``advection == False``.  All arrays are modified in place.
    """
    ny, nx = eta.shape

    # ---- cell-centre total depth + edge interpolations ----
    h_c = np.empty((ny, nx))
    for j in range(ny):
        for i in range(nx):
            d = h[j, i] + eta[j, i]
            h_c[j, i] = d if d > h_min else h_min

    h_u = np.empty((ny, nx + 1))
    for j in range(ny):
        for i in range(nx + 1):
            iL = i - 1 if i > 0 else 0
            iR = i if i < nx else nx - 1
            h_u[j, i] = 0.5 * (h_c[j, iL] + h_c[j, iR])

    h_v = np.empty((ny + 1, nx))
    for i in range(nx):
        for j in range(ny + 1):
            jL = j - 1 if j > 0 else 0
            jR = j if j < ny else ny - 1
            h_v[j, i] = 0.5 * (h_c[jL, i] + h_c[jR, i])

    # ---- u-momentum ----
    for j in range(ny):
        for i in range(nx + 1):
            if not mask_u[j, i]:
                u[j, i] = 0.0
                continue
            iL = i - 1 if i > 0 else 0
            iR = i if i < nx else nx - 1

            # pressure gradient (edges are zero-gradient)
            dpdx = 0.0
            if 0 < i < nx:
                dpdx = (eta[j, iR] - eta[j, iL]) / dx

            # v interpolated to this u-point
            if i == 0:
                v_interp = 0.5 * (v[j, 0] + v[j + 1, 0])
            elif i == nx:
                v_interp = 0.5 * (v[j, nx - 1] + v[j + 1, nx - 1])
            else:
                v_interp = 0.25 * (
                    v[j, i] + v[j, i - 1] + v[j + 1, i] + v[j + 1, i - 1]
                )

            h_u_pt = h_u[j, i]
            inv_h = 1.0 / (h_u_pt if h_u_pt > h_min else h_min)
            u_speed = np.sqrt(u[j, i] * u[j, i] + v_interp * v_interp)

            du_dt = -g * dpdx + f_u[j, i] * v_interp - cd * u[j, i] * u_speed * inv_h
            friction = dt * cd * u_speed * inv_h
            u[j, i] = (u[j, i] + dt * du_dt) / (1.0 + friction)

    # ---- v-momentum ----
    for j in range(ny + 1):
        for i in range(nx):
            if not mask_v[j, i]:
                v[j, i] = 0.0
                continue
            jL = j - 1 if j > 0 else 0
            jR = j if j < ny else ny - 1

            # pressure gradient (edges are zero-gradient)
            dpdy = 0.0
            if 0 < j < ny:
                dpdy = (eta[jR, i] - eta[jL, i]) / dy

            # u interpolated to this v-point
            if j == 0:
                u_interp = 0.5 * (u[0, i] + u[0, i + 1])
            elif j == ny:
                u_interp = 0.5 * (u[ny - 1, i] + u[ny - 1, i + 1])
            else:
                u_interp = 0.25 * (
                    u[j - 1, i] + u[j - 1, i + 1] + u[j, i] + u[j, i + 1]
                )

            h_v_pt = h_v[j, i]
            inv_h = 1.0 / (h_v_pt if h_v_pt > h_min else h_min)
            v_speed = np.sqrt(u_interp * u_interp + v[j, i] * v[j, i])

            dv_dt = -g * dpdy - f_v[j, i] * u_interp - cd * v[j, i] * v_speed * inv_h
            friction = dt * cd * v_speed * inv_h
            v[j, i] = (v[j, i] + dt * dv_dt) / (1.0 + friction)

    # ---- continuity (eta update on interior wet cells) ----
    for j in range(ny):
        for i in range(nx):
            if not mask[j, i]:
                eta[j, i] = 0.0
            elif not open_boundary[j, i]:
                flx_x = h_u[j, i + 1] * u[j, i + 1] - h_u[j, i] * u[j, i]
                flx_y = h_v[j + 1, i] * v[j + 1, i] - h_v[j, i] * v[j, i]
                eta[j, i] -= dt * (flx_x / dx + flx_y / dy)
