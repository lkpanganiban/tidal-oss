"""Tidal boundary-condition generation from FES2014 / TPXO harmonics.

Supports:
- Reading constituent amplitude & phase from NetCDF files.
- Interpolating harmonics to model grid open-boundary cells.
- Reconstructing elevation time series: eta(t) = sum A_k * cos(w_k * t + phi_k).
"""

from __future__ import annotations

import dataclasses

import numpy as np

ASTRO_FREQUENCIES: dict[str, float] = {
    "M2": 2.0 * np.pi / (12.4206012 * 3600.0),
    "S2": 2.0 * np.pi / (12.0 * 3600.0),
    "K1": 2.0 * np.pi / (23.9344696 * 3600.0),
    "O1": 2.0 * np.pi / (25.8193417 * 3600.0),
    "N2": 2.0 * np.pi / (12.6583482 * 3600.0),
    "K2": 2.0 * np.pi / (11.9672348 * 3600.0),
    "P1": 2.0 * np.pi / (24.0658902 * 3600.0),
    "Q1": 2.0 * np.pi / (26.8683567 * 3600.0),
    "M4": 2.0 * np.pi / (6.2103006 * 3600.0),
}


@dataclasses.dataclass
class TidalConstituent:
    """Amplitude and phase for one tidal harmonic at a set of spatial points."""

    name: str
    amplitude: np.ndarray  # [m]
    phase: np.ndarray  # [radians]
    omega: float  # [rad/s]
    lon: np.ndarray
    lat: np.ndarray

    @property
    def n_pts(self) -> int:
        return self.amplitude.size


@dataclasses.dataclass
class TidalBoundary:
    """Tidal elevation time series for a set of boundary cells."""

    constituents: list[TidalConstituent]
    n_boundary_cells: int
    amp: np.ndarray  # shape (n_constituents, n_boundary_cells)
    phase: np.ndarray  # shape (n_constituents, n_boundary_cells)
    omega: np.ndarray  # shape (n_constituents,)
    names: list[str]

    def evaluate(self, t_seconds: np.ndarray) -> np.ndarray:
        """Compute eta(t) for all boundary cells.

        Parameters
        ----------
        t_seconds : ndarray (nt,)
            Times in seconds from simulation start.

        Returns
        -------
        eta : ndarray (nt, n_boundary_cells)
            Free-surface elevation [m].
        """
        nt = len(t_seconds)
        nc = len(self.names)
        nb = self.n_boundary_cells

        eta = np.zeros((nt, nb))
        for k in range(nc):
            omega_t = np.outer(t_seconds, np.ones(nb)) * self.omega[k]
            phase = self.phase[k, :]
            amp = self.amp[k, :]
            eta += amp * np.cos(omega_t + phase)
        return eta

    def evaluate_at(self, t_seconds: float) -> np.ndarray:
        """Compute eta at a single time for all boundary cells.

        Returns
        -------
        eta : ndarray (n_boundary_cells,)
        """
        eta = np.zeros(self.n_boundary_cells)
        for k in range(len(self.names)):
            eta += self.amp[k, :] * np.cos(self.omega[k] * t_seconds + self.phase[k, :])
        return eta


def _interp_to_boundary(
    lat_grid: np.ndarray,
    lon_grid: np.ndarray,
    amp_field: np.ndarray,
    pha_field: np.ndarray,
    lon_bnd: np.ndarray,
    lat_bnd: np.ndarray,
    fill_value: float | None = 0.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Bilinear-interpolate amplitude & phase grids to boundary points.

    Parameters
    ----------
    lat_grid, lon_grid : ndarray
        1-D source coordinates (in interpolation order).
    amp_field, pha_field : ndarray
        Source amplitude [m] and phase [rad] fields.
    lon_bnd, lat_bnd : ndarray
        Boundary-cell coordinates to interpolate to.
    fill_value : float or None
        Value for out-of-domain points (None = nearest extrapolation).

    Returns
    -------
    amp : ndarray
        Amplitude at boundary points [m].
    pha : ndarray
        Phase at boundary points [rad].
    """
    from scipy.interpolate import RegularGridInterpolator

    interp_amp = RegularGridInterpolator(
        (lat_grid, lon_grid), amp_field, bounds_error=False, fill_value=fill_value
    )
    interp_pha = RegularGridInterpolator(
        (lat_grid, lon_grid), pha_field, bounds_error=False, fill_value=fill_value
    )

    pts = np.column_stack([lat_bnd, lon_bnd])
    return interp_amp(pts), interp_pha(pts)


def read_fes_constituents(
    path: str,
    constituents: list[str],
    lon_bnd: np.ndarray,
    lat_bnd: np.ndarray,
) -> list[TidalConstituent]:
    """Read FES2014 amplitude & phase and interpolate to boundary coordinates.

    Parameters
    ----------
    path : str
        Directory containing per-constituent NetCDF files, e.g.
        ``fes2014/M2_ocean.nc``, ``fes2014/M2_load.nc``.
    constituents : list[str]
        Constituent names, e.g. ["M2", "S2", "K1", "O1"].
    lon_bnd, lat_bnd : ndarray
        Coordinates of boundary cells to interpolate to.

    Returns
    -------
    constituents : list[TidalConstituent]
    """
    import os

    import xarray as xr

    result = []
    for name in constituents:
        amp_file = os.path.join(path, f"{name}_ocean.nc")
        if not os.path.isfile(amp_file):
            raise FileNotFoundError(f"FES2014 amplitude file not found: {amp_file}")

        ds_amp = xr.open_dataset(amp_file, decode_times=False)
        ds_pha = xr.open_dataset(
            os.path.join(path, f"{name}_load.nc"), decode_times=False
        )

        lon_fes = ds_amp["lon"].values
        lat_fes = ds_amp["lat"].values

        amp_raw = ds_amp["ocean_amplitude"].values
        pha_raw = ds_pha["load_phase"].values

        amp, pha_deg = _interp_to_boundary(
            lat_fes,
            lon_fes,
            amp_raw.squeeze(),
            pha_raw.squeeze(),
            lon_bnd,
            lat_bnd,
            fill_value=None,
        )
        pha = np.deg2rad(pha_deg)

        omega = ASTRO_FREQUENCIES.get(name)
        if omega is None:
            raise ValueError(f"Unknown constituent: {name}")

        result.append(
            TidalConstituent(
                name=name,
                amplitude=amp,
                phase=pha,
                omega=omega,
                lon=lon_bnd.copy(),
                lat=lat_bnd.copy(),
            )
        )

        ds_amp.close()
        ds_pha.close()

    return result


def build_tidal_boundary(
    constituents: list[TidalConstituent],
) -> TidalBoundary:
    """Pack per-constituent data into a single TidalBoundary object."""
    if not constituents:
        raise ValueError("At least one constituent is required.")

    nc = len(constituents)
    nb = constituents[0].n_pts

    amp = np.zeros((nc, nb))
    phase = np.zeros((nc, nb))
    omega = np.zeros(nc)
    names = []

    for k, c in enumerate(constituents):
        if c.n_pts != nb:
            raise ValueError(
                f"Constituent {c.name} has {c.n_pts} points, expected {nb}."
            )
        amp[k, :] = c.amplitude
        phase[k, :] = c.phase
        omega[k] = c.omega
        names.append(c.name)

    return TidalBoundary(
        constituents=constituents,
        n_boundary_cells=nb,
        amp=amp,
        phase=phase,
        omega=omega,
        names=names,
    )


def read_got_constituents(
    path: str,
    constituents: list[str],
    lon_bnd: np.ndarray,
    lat_bnd: np.ndarray,
) -> list[TidalConstituent]:
    """Read GOT4.10c harmonic data from per-constituent NetCDF files.

    GOT4.10c netCDF format (0.5° global grid):
      - ``latitude`` (1-D, len 361), ``longitude`` (1-D, len 720)
      - ``amplitude`` (lat, lon) in **centimetres**
      - ``phase`` (lat, lon) in **degrees**

    Filenames are lower-case: ``m2.nc``, ``s2.nc``, ``k1.nc``, ``o1.nc``, etc.

    Parameters
    ----------
    path : str
        Directory containing per-constituent GOT netCDF files.
    constituents : list[str]
        Constituent names, e.g. ["M2", "S2", "K1", "O1"].
    lon_bnd, lat_bnd : ndarray
        Coordinates of boundary cells to interpolate to.

    Returns
    -------
    list[TidalConstituent]
    """
    import os

    import xarray as xr

    result = []
    for name in constituents:
        nc_file = os.path.join(path, f"{name.lower()}.nc")
        if not os.path.isfile(nc_file):
            raise FileNotFoundError(f"GOT constituent file not found: {nc_file}")

        ds = xr.open_dataset(nc_file, decode_times=False)

        lon_got = ds["longitude"].values.astype(np.float64)
        lat_got = ds["latitude"].values.astype(np.float64)
        amp_raw = np.nan_to_num(
            ds["amplitude"].values.astype(np.float64) / 100.0, nan=0.0
        )
        pha_raw = np.nan_to_num(ds["phase"].values.astype(np.float64), nan=0.0)

        amp, pha_deg = _interp_to_boundary(
            lat_got, lon_got, amp_raw, pha_raw, lon_bnd, lat_bnd, fill_value=0.0
        )
        pha = np.deg2rad(pha_deg)

        omega = ASTRO_FREQUENCIES.get(name.upper())
        if omega is None:
            raise ValueError(f"Unknown constituent: {name}")

        result.append(
            TidalConstituent(
                name=name.upper(),
                amplitude=amp,
                phase=pha,
                omega=omega,
                lon=lon_bnd.copy(),
                lat=lat_bnd.copy(),
            )
        )

        ds.close()

    return result


def read_tpxo_constituents(
    path: str,
    constituents: list[str],
    lon_bnd: np.ndarray,
    lat_bnd: np.ndarray,
) -> list[TidalConstituent]:
    """Read TPXO9 harmonic data and interpolate to boundary coordinates.

    TPXO9 stores all constituents in a single NetCDF file with real (hRe)
    and imaginary (hIm) parts.  Amplitude and phase are reconstructed as:
        A = sqrt(hRe² + hIm²)
        φ = atan2(-hIm, hRe)

    Parameters
    ----------
    path : str
        Path to the TPXO grid NetCDF, e.g. ``data/tpxo9/h_tpxo9.v1.nc``.
    constituents : list[str]
        Constituent names to extract, e.g. ["m2", "s2", "k1", "o1"].
        Matching is case-insensitive.
    lon_bnd, lat_bnd : ndarray
        Coordinates of boundary cells to interpolate to.

    Returns
    -------
    constituents : list[TidalConstituent]
    """
    import os

    import xarray as xr

    if not os.path.isfile(path):
        raise FileNotFoundError(f"TPXO grid file not found: {path}")

    ds = xr.open_dataset(path, decode_times=False)

    lon_var = _find_coord(ds, ["lon", "lon_z", "longitude", "x"])
    lat_var = _find_coord(ds, ["lat", "lat_z", "latitude", "y"])
    con_var = _find_any(ds, ["con", "constituent", "constituents"])
    if con_var is None:
        raise KeyError(
            "Cannot find constituent name variable in TPXO file. "
            "Expected 'con', 'constituent', or 'constituents'."
        )

    lon_grid = ds[lon_var].values.astype(np.float64)
    lat_grid = ds[lat_var].values.astype(np.float64)

    con_names = _read_constituent_names(ds, con_var)

    idx_map = _build_constituent_index(con_names, constituents)

    hRe = _get_arr(ds, ["hRe", "hz_real", "h_real"])
    hIm = _get_arr(ds, ["hIm", "hz_imag", "h_imag"])

    hRe, hIm, con_axis = _normalise_tpxo_dims(hRe, hIm, len(con_names))

    result = []
    for name in constituents:
        k = idx_map[name.lower()]
        amp_raw = np.sqrt(hRe[k] ** 2 + hIm[k] ** 2)
        pha_raw = np.arctan2(-hIm[k], hRe[k])

        amp, pha = _interp_to_boundary(
            lat_grid, lon_grid, amp_raw, pha_raw, lon_bnd, lat_bnd, fill_value=0.0
        )

        omega = ASTRO_FREQUENCIES.get(name.upper(), ASTRO_FREQUENCIES.get(name))
        if omega is None:
            raise ValueError(f"Unknown constituent: {name}")

        result.append(
            TidalConstituent(
                name=name.upper(),
                amplitude=amp,
                phase=pha,
                omega=omega,
                lon=lon_bnd.copy(),
                lat=lat_bnd.copy(),
            )
        )

    ds.close()
    return result


def _find_coord(ds, candidates: list[str]) -> str:
    for name in candidates:
        if name in ds.coords or name in ds.dims:
            return name
    raise KeyError(f"No coordinate found among {candidates} in TPXO dataset.")


def _find_any(ds, candidates: list[str]) -> str | None:
    for name in candidates:
        if name in ds.coords or name in ds.dims or name in ds.data_vars or name in ds:
            return name
    return None


def _get_arr(ds, candidates: list[str]) -> np.ndarray:
    for name in candidates:
        if name in ds.data_vars:
            return ds[name].values
        if name in ds:
            return ds[name].values
    raise KeyError(f"No data variable found among {candidates} in TPXO dataset.")


def _read_constituent_names(ds, con_var: str) -> list[str]:
    raw = ds[con_var].values
    names = []
    if raw.dtype.kind in ("S", "U"):
        for c in raw:
            if isinstance(c, (bytes, bytearray)):
                names.append(c.decode("utf-8").strip().lower())
            elif isinstance(c, str):
                names.append(c.strip().lower())
            else:
                s = "".join(str(ch) for ch in c.flat).strip().lower()
                names.append(s)
    else:
        names = [str(c).strip().lower() for c in raw]
    return names


def _build_constituent_index(
    con_names: list[str], requested: list[str]
) -> dict[str, int]:
    lower_names = [n.lower() for n in con_names]
    idx_map = {}
    for name in requested:
        key = name.lower()
        if key in lower_names:
            idx_map[key] = lower_names.index(key)
        else:
            raise ValueError(
                f"Constituent '{name}' not found in TPXO file. Available: {con_names}"
            )
    return idx_map


def _normalise_tpxo_dims(
    hRe: np.ndarray, hIm: np.ndarray, ncon: int
) -> tuple[np.ndarray, np.ndarray, int]:
    if hRe.ndim == 3:
        if hRe.shape[0] == ncon:
            return hRe, hIm, 0
        elif hRe.shape[-1] == ncon:
            return hRe, hIm, -1
    elif hRe.ndim == 2:
        return hRe[np.newaxis, :, :], hIm[np.newaxis, :, :], 0
    raise ValueError(
        f"Unexpected TPXO array shape: hRe {hRe.shape}, expected "
        f"(ncon, nlat, nlon) or (nlat, nlon, ncon)."
    )


def read_tidal_constituents(
    source: str,
    path: str,
    constituents: list[str],
    lon_bnd: np.ndarray,
    lat_bnd: np.ndarray,
) -> list[TidalConstituent]:
    """Dispatch to the correct reader based on the tidal source.

    Parameters
    ----------
    source : str
        One of ``"fes2014"``, ``"tpxo9"``, ``"tpxo"``.
    path : str
        Directory (FES) or file path (TPXO).
    constituents : list[str]
        Constituent names.
    lon_bnd, lat_bnd : ndarray
        Boundary cell coordinates.

    Returns
    -------
    list[TidalConstituent]
    """
    source_lower = source.lower()
    if source_lower in ("fes2014", "fes"):
        return read_fes_constituents(path, constituents, lon_bnd, lat_bnd)
    elif source_lower in ("tpxo9", "tpxo"):
        return read_tpxo_constituents(path, constituents, lon_bnd, lat_bnd)
    elif source_lower in ("got", "got4.10c", "got4.10", "got410c"):
        return read_got_constituents(path, constituents, lon_bnd, lat_bnd)
    else:
        raise ValueError(
            f"Unknown tidal source: {source}. "
            f"Supported: fes2014, tpxo9, got (GOT4.10c)."
        )


def make_synthetic_tidal_boundary(
    n_boundary_cells: int,
    amplitude: float = 0.5,
    constituents: list[str] | None = None,
) -> TidalBoundary:
    """Create a synthetic tidal boundary with uniform amplitude and zero phase.

    Useful for idealised test cases where real harmonic data is not needed.
    """
    if constituents is None:
        constituents = ["M2"]

    nc = len(constituents)
    nb = n_boundary_cells
    amp = np.zeros((nc, nb))
    phase = np.zeros((nc, nb))
    omega = np.zeros(nc)
    names = []

    for k, name in enumerate(constituents):
        amp[k, :] = amplitude
        phase[k, :] = 0.0
        omega[k] = ASTRO_FREQUENCIES[name]
        names.append(name)

    const_list = [
        TidalConstituent(
            name=n,
            amplitude=amp[k, :],
            phase=phase[k, :],
            omega=omega[k],
            lon=np.arange(nb, dtype=float),
            lat=np.zeros(nb),
        )
        for k, n in enumerate(names)
    ]

    return TidalBoundary(
        constituents=const_list,
        n_boundary_cells=nb,
        amp=amp,
        phase=phase,
        omega=omega,
        names=names,
    )
