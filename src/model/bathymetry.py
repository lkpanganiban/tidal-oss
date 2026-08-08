"""GEBCO bathymetry loading, clipping, and regridding.

All operations are lazy (xarray) where possible.  The module assumes a
GEBCO 2024 global NetCDF is available locally; alternative raster formats
can be handled by the generic `load_bathymetry_raster` entry point.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import xarray as xr
from scipy.interpolate import RegularGridInterpolator


def load_gebco(
    path: str,
    lon_min: float = 116.0,
    lon_max: float = 130.0,
    lat_min: float = 4.0,
    lat_max: float = 22.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Load and clip GEBCO bathymetry to a bounding box.

    Parameters
    ----------
    path : str
        Path to GEBCO_2024.nc (or clipped subset).
    lon_min, lon_max : float
        Longitude bounds.
    lat_min, lat_max : float
        Latitude bounds.

    Returns
    -------
    lon : ndarray (nx,)
    lat : ndarray (ny,)
    elevation : ndarray (ny, nx)
        Bathymetry [m], positive up (GEBCO convention).  Values > 0 are land.
    """
    ds = xr.open_dataset(path, decode_times=False)

    lon_var = _find_coord(ds, ["lon", "longitude", "x"])
    lat_var = _find_coord(ds, ["lat", "latitude", "y"])
    elev_var = _find_data_var(ds)

    lon = ds[lon_var].values.astype(np.float64)
    lat = ds[lat_var].values.astype(np.float64)

    if lon_min > lon_max:
        lon_mask = (lon >= lon_min) | (lon <= lon_max)
    else:
        lon_mask = (lon >= lon_min) & (lon <= lon_max)
    lat_mask = (lat >= lat_min) & (lat <= lat_max)

    lon = lon[lon_mask]
    lat = lat[lat_mask]

    if len(lon) == 0 or len(lat) == 0:
        raise ValueError(
            f"No GEBCO data in bbox: "
            f"lon=[{lon_min},{lon_max}], lat=[{lat_min},{lat_max}]"
        )

    elevation = (
        ds[elev_var]
        .sel({lon_var: lon, lat_var: lat}, method="nearest")
        .values.astype(np.float64)
    )

    if elevation.ndim == 2 and (
        elevation.shape[0] != len(lat) or elevation.shape[1] != len(lon)
    ):
        elevation = elevation.T

    ds.close()
    return lon, lat, elevation


def regrid_bathymetry(
    lon_src: np.ndarray,
    lat_src: np.ndarray,
    elevation_src: np.ndarray,
    resolution_km: float = 2.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Coarsen bathymetry to a coarser uniform grid.

    Parameters
    ----------
    lon_src, lat_src : ndarray
        Source coordinates (1-D).
    elevation_src : ndarray (ny_src, nx_src)
        Source bathymetry (positive up).
    resolution_km : float
        Target grid spacing in km (applied to both lon and lat).

    Returns
    -------
    lon_new : ndarray (nx_new,)
    lat_new : ndarray (ny_new,)
    elev_new : ndarray (ny_new, nx_new)
    """
    dlon = resolution_km / 111.32
    dlat = resolution_km / 111.32

    lon_min, lon_max = lon_src.min(), lon_src.max()
    lat_min, lat_max = lat_src.min(), lat_src.max()

    nx = max(2, int(np.ceil((lon_max - lon_min) / dlon)))
    ny = max(2, int(np.ceil((lat_max - lat_min) / dlat)))

    lon_new = np.linspace(lon_min, lon_max, nx)
    lat_new = np.linspace(lat_min, lat_max, ny)

    if elevation_src.ndim == 2:
        if elevation_src.shape[0] == len(lat_src) and elevation_src.shape[1] == len(
            lon_src
        ):
            interp = RegularGridInterpolator(
                (lat_src, lon_src),
                elevation_src,
                bounds_error=False,
                fill_value=None,
            )
            lon_grid, lat_grid = np.meshgrid(lon_new, lat_new)
            pts = np.column_stack([lat_grid.ravel(), lon_grid.ravel()])
            elev_new = interp(pts).reshape(ny, nx)
        else:
            elev_new = _simple_bin(elevation_src, ny, nx)
    else:
        elev_new = _simple_bin(elevation_src, ny, nx)

    return lon_new, lat_new, elev_new


def elevation_to_depth(elevation: np.ndarray) -> np.ndarray:
    """Convert GEBCO elevation (positive up) to depth (positive down).

    Land cells (elevation > 0) are set to zero depth and must be masked
    separately using a land-mask routine.
    """
    return np.maximum(-elevation, 0.0)


def build_land_mask(
    lon_1d: np.ndarray,
    lat_1d: np.ndarray,
    land_shapefile_path: str,
) -> np.ndarray:
    """Rasterise a land-polygon shapefile onto the model grid.

    Uses ``rasterio.features.rasterize`` to burn polygon interiors onto
    a boolean mask that matches the shape ``(len(lat_1d), len(lon_1d))``.

    Parameters
    ----------
    lon_1d : ndarray (nx,)
        Longitude centres for each column.
    lat_1d : ndarray (ny,)
        Latitude centres for each row (south to north).
    land_shapefile_path : str
        Path to a land-polygon shapefile (EPSG:4326).

    Returns
    -------
    mask : ndarray (ny, nx), bool
        True where the cell overlaps with a land polygon.
    """
    import fiona
    from affine import Affine
    from rasterio.features import rasterize

    if not Path(land_shapefile_path).exists():
        raise FileNotFoundError(f"Shapefile not found: {land_shapefile_path}")

    nx = len(lon_1d)
    ny = len(lat_1d)

    dlon = (lon_1d[-1] - lon_1d[0]) / (nx - 1) if nx > 1 else 1.0
    dlat = (lat_1d[-1] - lat_1d[0]) / (ny - 1) if ny > 1 else 1.0

    lon_ul = lon_1d[0] - dlon / 2.0
    lat_ul = lat_1d[-1] + dlat / 2.0

    transform = Affine(dlon, 0.0, lon_ul, 0.0, -dlat, lat_ul)

    with fiona.open(land_shapefile_path) as src:
        if src.crs and not _is_geographic(src.crs):
            raise ValueError(
                f"Shapefile CRS must be geographic (EPSG:4326), got: {src.crs}"
            )
        geoms = [(feat["geometry"], 1) for feat in src]

    rasterised = rasterize(
        geoms,
        out_shape=(ny, nx),
        transform=transform,
        fill=0,
        dtype="uint8",
    )

    return rasterised[::-1, :].astype(bool)


def _is_geographic(crs) -> bool:
    """Return True if *crs* is a geographic (lat/lon) coordinate system."""
    try:
        return crs.is_geographic
    except AttributeError:
        pass
    if hasattr(crs, "to_dict"):
        d = crs.to_dict()
    elif isinstance(crs, dict):
        d = crs
    else:
        return False
    init = d.get("init", "").lower()
    if init == "epsg:4326":
        return True
    no_defs = d.get("no_defs", False)
    proj = d.get("proj", "").lower()
    return proj in ("longlat", "latlong") and not no_defs


def _find_coord(ds: xr.Dataset, candidates: list[str]) -> str:
    for name in candidates:
        if name in ds.coords or name in ds.dims:
            return name
    raise KeyError(f"No coordinate found among {candidates} in dataset.")


def _find_data_var(ds: xr.Dataset) -> str:
    skip = set(ds.coords) | set(ds.dims)
    spatial: str | None = None
    for name in ds.data_vars:
        name = str(name)
        if name in skip:
            continue
        ndim = ds[name].ndim
        if ndim >= 2:
            return name
        spatial = spatial or name
    if spatial is not None:
        return spatial
    raise KeyError("No data variable found in GEBCO dataset.")


def _simple_bin(arr: np.ndarray, ny: int, nx: int) -> np.ndarray:
    """Coarse-grain by block averaging (vectorised).

    Pads the source array with edge values up to a multiple of the target
    shape, then reshapes into (ny, ny_block, nx, nx_block) blocks and
    averages each block.  Block sizes may differ by at most one cell,
    matching the semantics of the original loop-based binning.
    """
    sy, sx = arr.shape
    if sy == 0 or sx == 0:
        return np.zeros((ny, nx))
    by = int(np.ceil(sy / ny))
    bx = int(np.ceil(sx / nx))
    pad_y = by * ny - sy
    pad_x = bx * nx - sx
    if pad_y > 0 or pad_x > 0:
        arr = np.pad(arr, ((0, pad_y), (0, pad_x)), mode="edge")
    return arr.reshape(ny, by, nx, bx).mean(axis=(1, 3))
