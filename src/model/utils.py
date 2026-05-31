"""Utility functions for the tidal hydrodynamic screening model.

Provides Coriolis parameter, stability criteria, array indexing helpers,
and interpolation routines used across the model package.
"""

import numpy as np


def coriolis(lat: np.ndarray | float) -> np.ndarray | float:
    """Coriolis parameter f = 2 * Omega * sin(lat).

    Parameters
    ----------
    lat : array or float
        Latitude in degrees.

    Returns
    -------
    f : array or float
        Coriolis parameter [rad/s].
    """
    omega = 7.2921159e-5
    return 2.0 * omega * np.sin(np.deg2rad(lat))


def cfl_timestep(dx: float, dy: float, h_max: float, safety: float = 0.5) -> float:
    """Maximum stable time step from the 2D CFL condition for surface gravity waves.

    Uses the 2D wave-speed formula: dt <= 1 / sqrt(1/dx² + 1/dy²) / sqrt(g * h).

    Parameters
    ----------
    dx, dy : float
        Grid spacing in x and y [m].
    h_max : float
        Maximum total water depth [m].
    safety : float
        Safety factor (default 0.5).

    Returns
    -------
    dt_max : float
        Maximum stable time step [s].
    """
    g = 9.81
    c_max = np.sqrt(g * max(h_max, 0.1))
    dx_eff = 1.0 / np.sqrt(1.0 / dx**2 + 1.0 / dy**2)
    return safety * dx_eff / c_max


def adams_bashforth3(
    f_n: np.ndarray,
    f_nm1: np.ndarray,
    f_nm2: np.ndarray,
) -> np.ndarray:
    """Third-order Adams-Bashforth extrapolation.

    Returns the AB3 estimate of the integral of f over one time step:
        f_AB3 = 23/12 * f_n - 16/12 * f_nm1 + 5/12 * f_nm2
    """
    return (23.0 * f_n - 16.0 * f_nm1 + 5.0 * f_nm2) / 12.0


def interpolate_to_u(phi: np.ndarray) -> np.ndarray:
    """Interpolate a cell-centre field to u-points (x-direction faces).

    phi has shape (ny, nx). Returns array of shape (ny, nx+1) where
    result[:, i] = average of phi[:, i-1] and phi[:, i] (one-sided at edges).
    """
    ny, nx = phi.shape
    result = np.zeros((ny, nx + 1), dtype=phi.dtype)
    result[:, 1:nx] = 0.5 * (phi[:, :-1] + phi[:, 1:])
    result[:, 0] = phi[:, 0]
    result[:, nx] = phi[:, nx - 1]
    return result


def interpolate_to_v(phi: np.ndarray) -> np.ndarray:
    """Interpolate a cell-centre field to v-points (y-direction faces).

    phi has shape (ny, nx). Returns array of shape (ny+1, nx) where
    result[j, :] = average of phi[j-1, :] and phi[j, :] (one-sided at edges).
    """
    ny, nx = phi.shape
    result = np.zeros((ny + 1, nx), dtype=phi.dtype)
    result[1:ny, :] = 0.5 * (phi[:-1, :] + phi[1:, :])
    result[0, :] = phi[0, :]
    result[ny, :] = phi[ny - 1, :]
    return result


def v_at_u_pts(v: np.ndarray) -> np.ndarray:
    """Interpolate v (at y-faces, shape ny+1 x nx) to u-points (ny x nx+1).

    Averages four surrounding v values at each u-point.
    """
    ny, nx = v.shape[0] - 1, v.shape[1]
    result = np.zeros((ny, nx + 1), dtype=v.dtype)
    result[:, 1:nx] = 0.25 * (
        v[:-1, 1:] + v[:-1, :-1] + v[1:, 1:] + v[1:, :-1]
    )
    result[:, 0] = 0.5 * (v[:-1, 0] + v[1:, 0])
    result[:, nx] = 0.5 * (v[:-1, nx - 1] + v[1:, nx - 1])
    return result


def u_at_v_pts(u: np.ndarray) -> np.ndarray:
    """Interpolate u (at x-faces, shape ny x nx+1) to v-points (ny+1 x nx).

    Averages four surrounding u values at each v-point.
    """
    ny, nx = u.shape[0], u.shape[1] - 1
    result = np.zeros((ny + 1, nx), dtype=u.dtype)
    result[1:ny, :] = 0.25 * (
        u[1:, :-1] + u[1:, 1:] + u[:-1, :-1] + u[:-1, 1:]
    )
    result[0, :] = 0.5 * (u[0, :-1] + u[0, 1:])
    result[ny, :] = 0.5 * (u[ny - 1, :-1] + u[ny - 1, 1:])
    return result


def velocity_at_centres(u: np.ndarray, v: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Average edge velocities to cell centres.

    u has shape (ny, nx+1), v has shape (ny+1, nx).
    Returns (u_c, v_c) each of shape (ny, nx).
    """
    u_c = 0.5 * (u[:, :-1] + u[:, 1:])
    v_c = 0.5 * (v[:-1, :] + v[1:, :])
    return u_c, v_c


def speed(u: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Depth-averaged speed |U| at cell centres.

    u (ny x nx+1), v (ny+1 x nx) -> result (ny x nx).
    """
    u_c, v_c = velocity_at_centres(u, v)
    return np.sqrt(u_c**2 + v_c**2)


def power_density(u: np.ndarray, v: np.ndarray, rho: float = 1025.0) -> np.ndarray:
    """Instantaneous tidal-current power density P = 0.5 * rho * U^3 [W/m^2].

    u (ny x nx+1), v (ny+1 x nx) -> result (ny x nx).
    """
    s = speed(u, v)
    return 0.5 * rho * s**3


def normalise_angle(radians: np.ndarray) -> np.ndarray:
    """Normalise angles to [-pi, pi]."""
    return np.arctan2(np.sin(radians), np.cos(radians))


def rotate_vector(
    u: np.ndarray, v: np.ndarray, angle_rad: float
) -> tuple[np.ndarray, np.ndarray]:
    """Rotate a 2D vector field by angle_rad anticlockwise."""
    cos_a = np.cos(angle_rad)
    sin_a = np.sin(angle_rad)
    u_rot = cos_a * u - sin_a * v
    v_rot = sin_a * u + cos_a * v
    return u_rot, v_rot
