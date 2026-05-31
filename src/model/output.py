"""NetCDF output writer and GeoTIFF power-density rasteriser."""

from __future__ import annotations

import numpy as np
import xarray as xr

from .grid import StructuredGrid
from .utils import speed


def create_results_dataset(
    grid: StructuredGrid,
    times: np.ndarray,
    eta_history: np.ndarray,
    u_history: np.ndarray,
    v_history: np.ndarray,
    power_history: np.ndarray | None = None,
) -> xr.Dataset:
    """Package a time series of model state into an xarray Dataset.

    Parameters
    ----------
    grid : StructuredGrid
    times : ndarray (nt,)
        Time in seconds since simulation start.
    eta_history : ndarray (nt, ny, nx)
    u_history : ndarray (nt, ny, nx+1)
    v_history : ndarray (nt, ny+1, nx)
    power_history : ndarray (nt, ny, nx) or None

    Returns
    -------
    ds : xr.Dataset
    """
    ds = xr.Dataset(
        data_vars={
            "eta": (["time", "y", "x"], eta_history),
            "u": (["time", "y", "x_u"], u_history),
            "v": (["time", "y_v", "x"], v_history),
        },
        coords={
            "time": times,
            "y": grid.y,
            "x": grid.x,
            "x_u": np.arange(grid.nx + 1) * grid.dx + grid.x[0] - grid.dx / 2,
            "y_v": np.arange(grid.ny + 1) * grid.dy + grid.y[0] - grid.dy / 2,
            "lat": (["y", "x"], grid.lat),
            "lon": (["y", "x"], grid.lon),
        },
    )

    ds["eta"].attrs = {"units": "m", "long_name": "free-surface elevation"}
    ds["u"].attrs = {"units": "m/s", "long_name": "depth-averaged x-velocity"}
    ds["v"].attrs = {"units": "m/s", "long_name": "depth-averaged y-velocity"}

    if power_history is not None:
        ds["power_density"] = (["time", "y", "x"], power_history)
        ds["power_density"].attrs = {
            "units": "W/m^2",
            "long_name": "tidal-current power density",
        }

    ds.attrs["rho"] = 1025.0
    ds.attrs["cd"] = 0.0025

    return ds


def write_netcdf(ds: xr.Dataset, path: str):
    """Write an xarray Dataset to NetCDF."""
    ds.to_netcdf(path, mode="w")


def write_mean_power_geotiff(
    grid: StructuredGrid,
    power_mean: np.ndarray,
    path: str,
):
    """Write a time-mean power-density array to a Cloud-Optimised GeoTIFF.

    Parameters
    ----------
    grid : StructuredGrid
    power_mean : ndarray (ny, nx)
        Time-mean power density [W/m²].
    path : str
        Output file path (.tif).
    """
    try:
        import rasterio
        from rasterio.transform import from_bounds
    except ImportError:
        raise ImportError(
            "rasterio is required for GeoTIFF output.  "
            "Install with: pip install rasterio"
        )

    lon = grid.lon
    lat = grid.lat

    lon_min = float(lon.min())
    lon_max = float(lon.max())
    lat_min = float(lat.min())
    lat_max = float(lat.max())

    ny, nx = power_mean.shape
    transform = from_bounds(lon_min, lat_min, lon_max, lat_max, nx, ny)

    with rasterio.open(
        path,
        "w",
        driver="COG",
        height=ny,
        width=nx,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=transform,
        TILING_SCHEME="GoogleMapsCompatible",
        COMPRESS="LZW",
    ) as dst:
        dst.write(power_mean.astype(np.float32), 1)
        dst.set_band_description(1, "mean tidal-current power density (W/m2)")


def write_hotspots_geojson(
    grid: StructuredGrid,
    power_mean: np.ndarray,
    threshold: float,
    path: str,
):
    """Export cells exceeding a power-density threshold as a GeoJSON point layer.

    Parameters
    ----------
    grid : StructuredGrid
    power_mean : ndarray (ny, nx)
    threshold : float
        Minimum power density to include [W/m²].
    path : str
        Output file path (.geojson).
    """
    import json

    features = []
    for j in range(grid.ny):
        for i in range(grid.nx):
            p = power_mean[j, i]
            if p >= threshold and grid.mask[j, i]:
                features.append(
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "Point",
                            "coordinates": [
                                float(grid.lon[j, i]),
                                float(grid.lat[j, i]),
                            ],
                        },
                        "properties": {
                            "power_density_Wm2": float(p),
                            "depth_m": float(grid.h[j, i]),
                        },
                    }
                )

    geojson = {"type": "FeatureCollection", "features": features}
    with open(path, "w") as f:
        json.dump(geojson, f, indent=2)
