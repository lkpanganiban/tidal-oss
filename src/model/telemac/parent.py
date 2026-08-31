"""One-way nesting: sample the parent screening solution at TELEMAC boundaries.

The Python screening model is the parent of every TELEMAC refinement.  Its
hourly ``results.nc`` holds the depth-averaged free-surface *and* velocity
evolution on the nationwide 2 km grid.  Imposing the parent's own elevation
**and velocity** at the refinement's liquid boundaries — Thompson-type nesting
(``OPTION FOR LIQUID BOUNDARIES : 2``) — makes the refinement a true nested
child of the screening run.  Elevation-only nesting systematically
under-drives the child: without the parent's boundary flow state the refined
currents fall to a fraction of the parent's.

Sampling uses the parent grid's wet mask: boundary points are interpolated
bilinearly only when all four bracketing parent cells are water, otherwise the
nearest wet parent cell is used, so coastline points are never blended with
land cells.
"""

from __future__ import annotations

import numpy as np

SEARCH_RADIUS_CELLS = 3


def _grid_axes(parent_nc: str):
    """Return (times, lat1d, lon1d) of the parent solution file."""
    from netCDF4 import Dataset

    with Dataset(parent_nc) as nc:
        times = np.asarray(nc["time"][:], dtype=np.float64)
        lat1d = np.asarray(nc["lat"][:, 0], dtype=np.float64)
        lon1d = np.asarray(nc["lon"][0, :], dtype=np.float64)
    if np.any(np.diff(lat1d) < 0) or np.any(np.diff(lon1d) < 0):
        raise ValueError("parent grid coordinates must be strictly ascending")
    return times, lat1d, lon1d


def _plan_samples(parent_grid, lat1d, lon1d, point_lon, point_lat):
    """Compute bracketing cells, weights and wet fallbacks for each point.

    Returns a dict with per-point index/weight arrays plus the bounding
    window (j0:j1, i0:i1) covering every cell the sampler will read.
    """
    point_lon = np.asarray(point_lon, dtype=np.float64)
    point_lat = np.asarray(point_lat, dtype=np.float64)
    if lat1d[0] > point_lat.min() or lat1d[-1] < point_lat.max():
        raise ValueError("parent grid does not cover the refinement in latitude")
    if lon1d[0] > point_lon.min() or lon1d[-1] < point_lon.max():
        raise ValueError("parent grid does not cover the refinement in longitude")

    wet = np.asarray(parent_grid.mask, dtype=bool)
    jj = np.clip(np.searchsorted(lat1d, point_lat) - 1, 0, len(lat1d) - 2)
    ii = np.clip(np.searchsorted(lon1d, point_lon) - 1, 0, len(lon1d) - 2)
    fy = np.clip((point_lat - lat1d[jj]) / (lat1d[jj + 1] - lat1d[jj]), 0.0, 1.0)
    fx = np.clip((point_lon - lon1d[ii]) / (lon1d[ii + 1] - lon1d[ii]), 0.0, 1.0)

    corners = ((jj, ii), (jj, ii + 1), (jj + 1, ii), (jj + 1, ii + 1))
    cwets = [wet[c] for c in corners]
    all_wet = cwets[0] & cwets[1] & cwets[2] & cwets[3]

    fallback_j = np.full(point_lon.shape, -1, dtype=np.int64)
    fallback_i = np.full(point_lon.shape, -1, dtype=np.int64)
    for p in np.where(~all_wet)[0]:
        j0, i0 = int(jj[p]), int(ii[p])
        for r in range(1, SEARCH_RADIUS_CELLS + 1):
            best = None
            best_d = np.inf
            for dj in range(-r, r + 1):
                for di in range(-r, r + 1):
                    if max(abs(dj), abs(di)) != r:
                        continue  # ring only
                    j, i = j0 + dj, i0 + di
                    if not (0 <= j < wet.shape[0] and 0 <= i < wet.shape[1]):
                        continue
                    if not wet[j, i]:
                        continue
                    d = (lat1d[j] - point_lat[p]) ** 2 + (lon1d[i] - point_lon[p]) ** 2
                    if d < best_d:
                        best_d = d
                        best = (j, i)
            if best is not None:
                fallback_j[p], fallback_i[p] = best
                break

    resolved = all_wet | (fallback_j >= 0)
    if not resolved.any():
        raise ValueError(
            "no wet parent cells near any liquid boundary point — the region "
            "box does not overlap the parent's wet domain"
        )

    j_all = np.concatenate([jj, jj + 1, fallback_j[fallback_j >= 0]])
    i_all = np.concatenate([ii, ii + 1, fallback_i[fallback_i >= 0]])
    return {
        "jj": jj,
        "ii": ii,
        "fy": fy,
        "fx": fx,
        "all_wet": all_wet,
        "fallback_j": fallback_j,
        "fallback_i": fallback_i,
        "resolved": resolved,
        "win": (
            int(j_all.min()),
            int(j_all.max()),
            int(i_all.min()),
            int(i_all.max()),
        ),
    }


def _read_window(parent_nc: str, var: str, win, pad_i: int = 0):
    from netCDF4 import Dataset

    j0, j1, i0, i1 = win
    with Dataset(parent_nc) as nc:
        arr = np.asarray(nc[var][:, j0 : j1 + 1, i0 : i1 + 1 + pad_i], dtype=np.float64)
    return arr


def _apply_weights(window, plan, npoints, nt):
    """Bilinear / nearest-wet assembly of (nt, npoints) from a window field."""
    jj, ii = plan["jj"], plan["ii"]
    fy, fx = plan["fy"], plan["fx"]
    all_wet, fj, fi = plan["all_wet"], plan["fallback_j"], plan["fallback_i"]
    j0, _, i0, _ = plan["win"]
    out = np.zeros((nt, npoints), dtype=np.float64)
    for p in np.where(all_wet)[0]:
        jr0, ir0 = jj[p] - j0, ii[p] - i0
        out[:, p] = (
            (1 - fy[p]) * (1 - fx[p]) * window[:, jr0, ir0]
            + (1 - fy[p]) * fx[p] * window[:, jr0, ir0 + 1]
            + fy[p] * (1 - fx[p]) * window[:, jr0 + 1, ir0]
            + fy[p] * fx[p] * window[:, jr0 + 1, ir0 + 1]
        )
    for p in np.where(~all_wet & (fj >= 0))[0]:
        out[:, p] = window[:, fj[p] - j0, fi[p] - i0]
    return out


def sample_parent_elevation(
    parent_nc: str,
    parent_grid,
    point_lon: np.ndarray,
    point_lat: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Sample parent ``eta`` at the given points.

    Returns (times, series (nt, npoints), resolved (npoints,) bool).
    """
    times, lat1d, lon1d = _grid_axes(parent_nc)
    plan = _plan_samples(parent_grid, lat1d, lon1d, point_lon, point_lat)
    eta = _read_window(parent_nc, "eta", plan["win"])
    series = _apply_weights(eta, plan, len(np.atleast_1d(point_lon)), times.size)
    return times, series, plan["resolved"]


def sample_parent_velocity(
    parent_nc: str,
    parent_grid,
    point_lon: np.ndarray,
    point_lat: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Sample parent cell-centred velocity (u, v) at the given points.

    The parent file stores C-grid face velocities (``u`` on x-faces,
    ``v`` on y-faces); both are averaged to cell centres first so the same
    bilinear/nearest-wet sampling as elevation applies.

    Returns (times, u_series, v_series) each (nt, npoints).
    """
    from netCDF4 import Dataset

    times, lat1d, lon1d = _grid_axes(parent_nc)
    plan = _plan_samples(parent_grid, lat1d, lon1d, point_lon, point_lat)
    j0, j1, i0, i1 = plan["win"]
    npoints = len(np.atleast_1d(point_lon))

    with Dataset(parent_nc) as nc:
        uwin = np.asarray(nc["u"][:, j0 : j1 + 1, i0 : i1 + 2], dtype=np.float64)
        vwin = np.asarray(nc["v"][:, j0 : j1 + 2, i0 : i1 + 1], dtype=np.float64)
    u_c = 0.5 * (uwin[:, :, :-1] + uwin[:, :, 1:])  # -> (nt, dj, di)
    v_c = 0.5 * (vwin[:, :-1, :] + vwin[:, 1:, :])
    u_series = _apply_weights(u_c, plan, npoints, times.size)
    v_series = _apply_weights(v_c, plan, npoints, times.size)
    return times, u_series, v_series


def read_parent_time_coverage(parent_nc: str) -> tuple[float, float]:
    """Return (first, last) parent snapshot times in seconds."""
    times, _, _ = _grid_axes(parent_nc)
    return float(times[0]), float(times[-1])
