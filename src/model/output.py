"""NetCDF output writer and GeoTIFF power-density rasteriser."""

from __future__ import annotations

import numpy as np
import xarray as xr

from .grid import StructuredGrid


class NetCDFStreamWriter:
    """Incrementally append model snapshots to a NetCDF file.

    The model run loop writes one snapshot (eta/u/v/power) per save
    interval without keeping the full time series in memory — important
    for production-scale grids where in-RAM snapshot stacks would exceed
    available memory.

    The ``time`` dimension is unlimited, so any number of snapshots can
    be appended.  Use :meth:`write_snapshot` from the solver callback and
    call :meth:`close` when done.
    """

    def __init__(
        self,
        path: str,
        grid: StructuredGrid,
        rho: float = 1025.0,
        cd: float = 0.0025,
        extra_attrs: dict | None = None,
        mode: str = "w",
    ):
        try:
            from netCDF4 import Dataset
        except ImportError:
            raise ImportError(
                "netCDF4 is required for streaming NetCDF output.  "
                "Install with: pip install netCDF4"
            ) from None

        self.path = path
        self.grid = grid
        self._nc = Dataset(path, mode, format="NETCDF4")  # type: ignore[arg-type]
        self._idx = 0
        if mode == "w":
            self._initialise(grid, rho, cd, extra_attrs)
        else:
            # Append mode: continue where the previous run left off.
            self._idx = len(self._nc.dimensions["time"])

    def _initialise(self, grid, rho, cd, extra_attrs):
        nc = self._nc
        ny, nx = grid.ny, grid.nx
        nc.createDimension("time", None)
        nc.createDimension("y", ny)
        nc.createDimension("x", nx)
        nc.createDimension("x_u", nx + 1)
        nc.createDimension("y_v", ny + 1)

        t = nc.createVariable("time", "f8", ("time",))
        t.units = "seconds since simulation start"
        y = nc.createVariable("y", "f8", ("y",))
        y.units = "m"
        x = nc.createVariable("x", "f8", ("x",))
        x.units = "m"
        x_u = nc.createVariable("x_u", "f8", ("x_u",))
        x_u.units = "m"
        y_v = nc.createVariable("y_v", "f8", ("y_v",))
        y_v.units = "m"
        lat = nc.createVariable("lat", "f8", ("y", "x"))
        lat.units = "degrees_north"
        lon = nc.createVariable("lon", "f8", ("y", "x"))
        lon.units = "degrees_east"

        eta = nc.createVariable("eta", "f4", ("time", "y", "x"), zlib=True)
        eta.units = "m"
        eta.long_name = "free-surface elevation"
        u = nc.createVariable("u", "f4", ("time", "y", "x_u"), zlib=True)
        u.units = "m/s"
        u.long_name = "depth-averaged x-velocity"
        v = nc.createVariable("v", "f4", ("time", "y_v", "x"), zlib=True)
        v.units = "m/s"
        v.long_name = "depth-averaged y-velocity"
        pwr = nc.createVariable("power_density", "f4", ("time", "y", "x"), zlib=True)
        pwr.units = "W/m^2"
        pwr.long_name = "tidal-current power density"

        y[:] = grid.y
        x[:] = grid.x
        x_u[:] = np.arange(grid.nx + 1) * grid.dx + grid.x[0] - grid.dx / 2
        y_v[:] = np.arange(grid.ny + 1) * grid.dy + grid.y[0] - grid.dy / 2
        lat[:] = grid.lat
        lon[:] = grid.lon

        nc.rho = rho
        nc.cd = cd
        for key, value in (extra_attrs or {}).items():
            setattr(nc, key, value)

    def write_snapshot(
        self,
        t: float,
        eta: np.ndarray,
        u: np.ndarray,
        v: np.ndarray,
        power: np.ndarray | None = None,
    ):
        """Append one snapshot at index ``self._idx`` (then increment)."""
        i = self._idx
        self._nc["time"][i] = t
        self._nc["eta"][i, :, :] = eta
        self._nc["u"][i, :, :] = u
        self._nc["v"][i, :, :] = v
        if power is not None:
            self._nc["power_density"][i, :, :] = power
        self._idx += 1

    def close(self):
        if self._nc is not None:
            self._nc.close()
            self._nc = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def read_last_state(path: str) -> tuple[float, np.ndarray, np.ndarray, np.ndarray]:
    """Read the most recent snapshot from an existing results NetCDF.

    Used by ``--resume`` to continue a run from where it left off.
    Returns (t, eta, u, v).
    """
    try:
        from netCDF4 import Dataset
    except ImportError:
        raise ImportError(
            "netCDF4 is required to read model state.  "
            "Install with: pip install netCDF4"
        ) from None

    with Dataset(path, "r") as nc:
        nt = len(nc.dimensions["time"])
        if nt == 0:
            raise ValueError(f"No snapshots found in {path}")
        i = nt - 1
        return (
            float(nc["time"][i]),
            np.asarray(nc["eta"][i, :, :]),
            np.asarray(nc["u"][i, :, :]),
            np.asarray(nc["v"][i, :, :]),
        )


def mean_power_from_netcdf(path: str) -> np.ndarray:
    """Time-mean power density over all snapshots in *path* (ny, nx).

    Used after a resumed run so the mean covers the full simulation, not
    just the most recent segment.
    """
    try:
        from netCDF4 import Dataset
    except ImportError:
        raise ImportError(
            "netCDF4 is required to read model state.  "
            "Install with: pip install netCDF4"
        ) from None

    with Dataset(path, "r") as nc:
        nt = len(nc.dimensions["time"])
        if nt == 0:
            raise ValueError(f"No snapshots found in {path}")
        power = np.asarray(nc["power_density"][:], dtype=np.float64)
    return power.mean(axis=0)


def max_speed_from_netcdf(path: str) -> np.ndarray:
    """Maximum depth-averaged current speed over all snapshots in *path*.

    Computed from the stored u/v histories; used after a resumed run so
    the maximum covers the full simulation.
    """
    try:
        from netCDF4 import Dataset
    except ImportError:
        raise ImportError(
            "netCDF4 is required to read model state.  "
            "Install with: pip install netCDF4"
        ) from None

    with Dataset(path, "r") as nc:
        nt = len(nc.dimensions["time"])
        if nt == 0:
            raise ValueError(f"No snapshots found in {path}")
        u = np.asarray(nc["u"][:], dtype=np.float64)
        v = np.asarray(nc["v"][:], dtype=np.float64)
    u_c = 0.5 * (u[:, :, :-1] + u[:, :, 1:])
    v_c = 0.5 * (v[:, :-1, :] + v[:, 1:, :])
    return np.sqrt(u_c**2 + v_c**2).max(axis=0)


def create_results_dataset(
    grid: StructuredGrid,
    times: np.ndarray,
    eta_history: np.ndarray,
    u_history: np.ndarray,
    v_history: np.ndarray,
    power_history: np.ndarray | None = None,
    rho: float = 1025.0,
    cd: float = 0.0025,
    extra_attrs: dict | None = None,
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
    rho : float
        Seawater density used for the power-density calculation [kg/m³].
    cd : float
        Bottom drag coefficient used in the run.
    extra_attrs : dict or None
        Additional global attributes (e.g. duration, constituents).

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

    ds.attrs["rho"] = rho
    ds.attrs["cd"] = cd
    if extra_attrs:
        ds.attrs.update(extra_attrs)

    return ds


def write_netcdf(ds: xr.Dataset, path: str):
    """Write an xarray Dataset to NetCDF."""
    ds.to_netcdf(path, mode="w")


def write_raster_geotiff(
    grid: StructuredGrid,
    values: np.ndarray,
    path: str,
    description: str,
    nodata: float | None = float("nan"),
):
    """Write any cell-centre field to a Cloud-Optimised GeoTIFF.

    Parameters
    ----------
    grid : StructuredGrid
    values : ndarray (ny, nx)
        Field to write (e.g. depth, max speed, distance to coast).
    path : str
        Output file path (.tif).
    description : str
        Band description / long name.
    nodata : float or None
        No-data marker.  Defaults to ``NaN`` so GIS tools (QGIS, GDAL) render
        masked regions as transparent rather than as spurious data.  Pass ``None``
        to omit the tag.
    """
    try:
        import rasterio
        from rasterio.transform import from_bounds
    except ImportError:
        raise ImportError(
            "rasterio is required for GeoTIFF output.  "
            "Install with: pip install rasterio"
        ) from None

    lon = grid.lon
    lat = grid.lat

    lon_min = float(lon.min())
    lon_max = float(lon.max())
    lat_min = float(lat.min())
    lat_max = float(lat.max())

    ny, nx = values.shape
    transform = from_bounds(lon_min, lat_min, lon_max, lat_max, nx, ny)

    # grid rows run south-to-north (row 0 = lat_min) while GeoTIFFs are
    # north-up (row 0 = lat_max); flip rows so the raster matches the
    # from_bounds transform.
    data = values[::-1, :]

    kwargs = dict(
        mode="w",
        driver="COG",
        height=ny,
        width=nx,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=transform,
        COMPRESS="LZW",
    )
    if nodata is not None:
        kwargs["nodata"] = nodata

    with rasterio.open(path, **kwargs) as dst:
        dst.write(data.astype(np.float32), 1)
        dst.set_band_description(1, description)


def write_mean_power_geotiff(
    grid: StructuredGrid,
    power_mean: np.ndarray,
    path: str,
):
    """Write a time-mean power-density array to a Cloud-Optimised GeoTIFF.

    Thin wrapper around :func:`write_raster_geotiff` (kept for backwards
    compatibility).

    Parameters
    ----------
    grid : StructuredGrid
    power_mean : ndarray (ny, nx)
        Time-mean power density [W/m²].
    path : str
        Output file path (.tif).
    """
    write_raster_geotiff(
        grid,
        power_mean,
        path,
        description="mean tidal-current power density (W/m2)",
    )


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

    above = (power_mean >= threshold) & grid.mask
    rows, cols = np.where(above)

    features = [
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
                "power_density_Wm2": float(power_mean[j, i]),
                "depth_m": float(grid.h[j, i]),
            },
        }
        for j, i in zip(rows, cols, strict=True)
    ]

    geojson = {"type": "FeatureCollection", "features": features}
    with open(path, "w") as f:
        json.dump(geojson, f, indent=2)
