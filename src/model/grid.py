"""Structured Arakawa C-grid definition and helper methods.

The grid stores bathymetric depth, the wet/dry mask, grid metrics at cell
centres, u-faces, and v-faces, plus coordinate arrays needed for Coriolis
and I/O.
"""

from __future__ import annotations

import dataclasses

import numpy as np

from .utils import coriolis, interpolate_to_u, interpolate_to_v


@dataclasses.dataclass
class StructuredGrid:
    """Regular structured grid for a 2D shallow-water model.

    All quantities use SI units (metres, seconds).  Depth *h* is positive
    downward (bathymetry convention).

    Attributes
    ----------
    nx, ny : int
        Number of cells in x and y.
    dx, dy : float
        Uniform grid spacing [m].
    x, y : ndarray
        Cell-centre coordinates in projected metres (shape (nx,), (ny,)).
    lon, lat : ndarray
        Cell-centre coordinates in degrees (shape (ny, nx)).
    h : ndarray (ny, nx)
        Bathymetric depth [m], positive down.
    mask : ndarray (ny, nx), bool
        True where the cell is wet (h >= min_depth & not land).
    f : ndarray (ny, nx)
        Coriolis parameter at cell centres [rad/s].
    h_u : ndarray (ny, nx+1)
        Depth interpolated to u-points.
    h_v : ndarray (ny+1, nx)
        Depth interpolated to v-points.
    mask_u : ndarray (ny, nx+1), bool
        Wet mask at u-points.
    mask_v : ndarray (ny+1, nx), bool
        Wet mask at v-points.
    open_boundary : ndarray (ny, nx), bool
        True where eta is prescribed (open boundary cell).
    """

    nx: int
    ny: int
    dx: float
    dy: float
    x: np.ndarray
    y: np.ndarray
    lon: np.ndarray
    lat: np.ndarray
    h: np.ndarray
    mask: np.ndarray
    f: np.ndarray
    h_u: np.ndarray
    h_v: np.ndarray
    mask_u: np.ndarray
    mask_v: np.ndarray
    open_boundary: np.ndarray

    @classmethod
    def from_uniform(
        cls,
        nx: int,
        ny: int,
        dx: float,
        dy: float,
        x0: float = 0.0,
        y0: float = 0.0,
        lat0: float = 0.0,
    ) -> StructuredGrid:
        """Create an empty grid with uniform spacing and a constant Coriolis.

        Useful for idealised test cases (channel, basin, etc.).
        """
        x = np.arange(nx) * dx + x0 + dx / 2
        y = np.arange(ny) * dy + y0 + dy / 2
        lon, lat_2d = np.meshgrid(x, y)
        lat_2d = np.full_like(lon, lat0)

        h = np.zeros((ny, nx))
        mask = np.ones((ny, nx), dtype=bool)
        open_boundary = np.zeros((ny, nx), dtype=bool)
        f_arr = np.full((ny, nx), coriolis(lat0))

        h_u = interpolate_to_u(h)
        h_v = interpolate_to_v(h)
        mask_u = np.ones((ny, nx + 1), dtype=bool)
        mask_v = np.ones((ny + 1, nx), dtype=bool)

        return cls(
            nx=nx,
            ny=ny,
            dx=dx,
            dy=dy,
            x=x,
            y=y,
            lon=lon,
            lat=lat_2d,
            h=h,
            mask=mask,
            f=f_arr,
            h_u=h_u,
            h_v=h_v,
            mask_u=mask_u,
            mask_v=mask_v,
            open_boundary=open_boundary,
        )

    @classmethod
    def from_bathymetry(
        cls,
        lon_1d: np.ndarray,
        lat_1d: np.ndarray,
        bathymetry: np.ndarray,
        land_mask: np.ndarray | None = None,
        min_depth: float = 2.0,
    ) -> StructuredGrid:
        """Build a grid from bathymetry arrays and optional land mask.

        Parameters
        ----------
        lon_1d : ndarray (nx,)
            Longitudes at cell centres.
        lat_1d : ndarray (ny,)
            Latitudes at cell centres.
        bathymetry : ndarray (ny, nx)
            Depth values [m], positive down.
        land_mask : ndarray (ny, nx) or None
            Optional boolean mask; True where land.
        min_depth : float
            Minimum depth to consider a cell wet [m].
        """
        ny, nx = bathymetry.shape
        if lon_1d.size != nx or lat_1d.size != ny:
            raise ValueError(
                f"Coordinate shape mismatch: lon {lon_1d.shape}, "
                f"lat {lat_1d.shape}, bathymetry {bathymetry.shape}"
            )

        lon_2d, lat_2d = np.meshgrid(lon_1d, lat_1d)

        h = np.maximum(bathymetry, 0.0).astype(np.float64)

        if land_mask is not None:
            mask = (h >= min_depth) & (~land_mask)
        else:
            mask = h >= min_depth

        h[~mask] = 0.0
        open_boundary = np.zeros((ny, nx), dtype=bool)
        open_boundary[0, :] = mask[0, :]
        open_boundary[-1, :] = mask[-1, :]
        open_boundary[:, 0] = mask[:, 0]
        open_boundary[:, -1] = mask[:, -1]

        f_arr = coriolis(lat_2d)

        h_u = interpolate_to_u(h)
        h_v = interpolate_to_v(h)
        mask_u = _build_u_mask(mask)
        mask_v = _build_v_mask(mask)

        dy_metres = _haversine_distance(lat_1d[0], lon_1d[0], lat_1d[-1], lon_1d[0])
        dx_metres = _haversine_distance(lat_1d[0], lon_1d[0], lat_1d[0], lon_1d[-1])
        dy_avg = dy_metres / (ny - 1) if ny > 1 else dy_metres
        dx_avg = dx_metres / (nx - 1) if nx > 1 else dx_metres

        x = np.arange(nx) * dx_avg
        y = np.arange(ny) * dy_avg

        return cls(
            nx=nx,
            ny=ny,
            dx=dx_avg,
            dy=dy_avg,
            x=x,
            y=y,
            lon=lon_2d,
            lat=lat_2d,
            h=h,
            mask=mask,
            f=f_arr,
            h_u=h_u,
            h_v=h_v,
            mask_u=mask_u,
            mask_v=mask_v,
            open_boundary=open_boundary,
        )

    @property
    def shape(self) -> tuple[int, int]:
        """Grid dimensions (ny, nx)."""
        return (self.ny, self.nx)

    @property
    def h_max(self) -> float:
        """Maximum depth in the domain [m]."""
        return float(np.max(self.h[self.mask])) if self.mask.any() else 0.0

    @property
    def h_min(self) -> float:
        """Minimum depth among wet cells [m]."""
        return float(np.min(self.h[self.mask])) if self.mask.any() else 0.0


def distance_to_coast_km(mask: np.ndarray, dx: float, dy: float) -> np.ndarray:
    """Distance from every cell to the nearest land cell, in km.

    Parameters
    ----------
    mask : ndarray (ny, nx), bool
        Wet-cell mask (True = water).
    dx, dy : float
        Grid spacing in x and y [m].

    Returns
    -------
    dist_km : ndarray (ny, nx)
        Distance to the nearest land cell [km]. Land cells = 0.
    """
    from scipy.ndimage import distance_transform_edt

    # scipy's EDT computes, for foreground (nonzero) pixels, the distance to
    # the nearest background pixel.  Land is the reference (background), so
    # the water mask is passed as foreground: water cells then report their
    # distance to the nearest land cell and land cells report 0.
    if not mask.any() or mask.all():
        return np.zeros(mask.shape, dtype=np.float64)
    dist_m = distance_transform_edt(mask, sampling=(dy, dx))
    return dist_m / 1000.0


def _build_u_mask(eta_mask: np.ndarray) -> np.ndarray:
    """Build the velocity mask at u-points from the cell-centre mask.

    A u-point is wet only if *both* adjacent cells are wet.
    """
    ny, nx = eta_mask.shape
    mask_u = np.zeros((ny, nx + 1), dtype=bool)
    mask_u[:, 1:nx] = eta_mask[:, :-1] & eta_mask[:, 1:]
    mask_u[:, 0] = eta_mask[:, 0]
    mask_u[:, nx] = eta_mask[:, nx - 1]
    return mask_u


def _build_v_mask(eta_mask: np.ndarray) -> np.ndarray:
    """Build the velocity mask at v-points from the cell-centre mask.

    A v-point is wet only if *both* adjacent cells are wet.
    """
    ny, nx = eta_mask.shape
    mask_v = np.zeros((ny + 1, nx), dtype=bool)
    mask_v[1:ny, :] = eta_mask[:-1, :] & eta_mask[1:, :]
    mask_v[0, :] = eta_mask[0, :]
    mask_v[ny, :] = eta_mask[ny - 1, :]
    return mask_v


def _haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance in metres between two lat/lon points (Haversine formula)."""
    R = 6371000.0
    dlat = np.deg2rad(lat2 - lat1)
    dlon = np.deg2rad(lon2 - lon1)
    a = (
        np.sin(dlat / 2) ** 2
        + np.cos(np.deg2rad(lat1)) * np.cos(np.deg2rad(lat2)) * np.sin(dlon / 2) ** 2
    )
    return R * 2.0 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))
