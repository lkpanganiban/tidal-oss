#!/usr/bin/env python3
"""Download the external datasets used by the Philippine tidal-energy workflow.

The downloader mirrors exactly what the model consumes (see
``src/model/config.yaml``) and the files already staged in ``data/``:

  GEBCO 2026            — Philippine-region bathymetry subset (NetCDF).
                         Fetched from a cloud-optimised GeoTIFF mirror on
                         ``data.source.coop`` via range requests, so only the
                         ~64 MB region window is downloaded (not the 7 GB
                         global grid).
  Philippines landmass  — ADM0 boundary GeoJSON from GeoBoundaries
                         (``data/philippines_landmass.geojson``).
  GOT4.10c              — NASA GSFC ocean tide model (per-constituent NetCDF,
                         no registration). Archive is auto-extracted.

FES2014 and TPXO9 remain registration-gated; the downloader prints the manual
steps but cannot automate them.

Usage:
  python downloader.py                  # guided interactive mode
  python downloader.py --all            # download everything that can be automated
  python downloader.py --gebco          # bathymetry only
  python downloader.py --landmask       # Philippines landmass only
  python downloader.py --tidal          # GOT4.10c + manual FES2014/TPXO9 steps
  python downloader.py --data-dir ./data  # custom output directory
"""

from __future__ import annotations

import argparse
import os
import shutil
import tarfile
import zipfile
from pathlib import Path
from urllib.request import urlretrieve

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PHILIPPINES_BBOX = {
    "lon_min": 112.0,
    "lon_max": 128.0,
    "lat_min": 4.0,
    "lat_max": 22.0,
}

# GeoBoundaries pinned release matching data/philippines_landmass.geojson
# (shapeID 24100683B85265433280220 = PHL ADM0 build of Dec 2023).
GEOBOUNDARIES_PHL_ADM0 = (
    "https://github.com/wmgeolab/geoBoundaries/raw/9469f09/releaseData/"
    "gbOpen/PHL/ADM0/geoBoundaries-PHL-ADM0_simplified.geojson"
)

# Cloud-optimised GEBCO 2026 grid (EPSG:4326, 15 arc-sec). giswqs mirror of the
# official NERC CEDA GEBCO_2026 grid. Official global NetCDF (7.4 GB) lives at:
#   https://dap.ceda.ac.uk/bodc/gebco/global/gebco_2026/ice_surface_elevation/netcdf/GEBCO_2026.nc
GEBCO_COG_URL = (
    "https://data.source.coop/giswqs/gebco-bathymetry/gebco_2026/gebco_2026.tif"
)

DATASETS: dict[str, dict] = {
    "gebco": {
        "name": "GEBCO 2026 bathymetry (Philippines subset)",
        "size_hint": "~64 MB (NetCDF, 15 arc-sec)",
        # Written to the same location src/model/config.yaml points at.
        "dest": "GEBCO_28_Aug_2026_0bcab7925fa2/gebco_2026_n22.0_s4.0_w112.0_e128.0.nc",
        "fetcher": "gebco_subset",
        "manual_url": GEBCO_COG_URL,
        "manual_note": (
            "Subset is read from a cloud-optimised GeoTIFF mirror of the "
            "official GEBCO 2026 grid using rasterio range requests. "
            "Requires: rasterio, xarray, netCDF4."
        ),
    },
    "landmask": {
        "name": "Philippines landmass (GeoBoundaries ADM0)",
        "size_hint": "~2.5 MB (GeoJSON)",
        "urls": [GEOBOUNDARIES_PHL_ADM0],
        "dest": "philippines_landmass.geojson",
        "manual_url": "https://www.geoboundaries.org/",
        "manual_note": (
            "Country boundary used to rasterise the land mask "
            "(bathymetry.land_shapefile in config.yaml)."
        ),
    },
    "got": {
        "name": "GOT4.10c tidal constituents (NASA GSFC)",
        "size_hint": "~44 MB (tar.gz; no registration)",
        "urls": [
            "https://earth.gsfc.nasa.gov/sites/default/files/2023-12/got4.10c.tar.gz",
        ],
        "dest": "got4.10c.tar.gz",
        "post_process": "untar_got",
        "manual_url": "https://earth.gsfc.nasa.gov/geo/data/ocean-tide-models",
        "manual_note": (
            "Extracted to data/GOT4.10c/; the model reads the per-constituent "
            "NetCDFs in data/GOT4.10c/grids_oceantide_netcdf/."
        ),
    },
    "fes2014": {
        "name": "FES2014 tidal constituents",
        "size_hint": "~2 GB (global per-constituent files)",
        "dest": None,
        "manual_url": (
            "https://www.aviso.altimetry.fr/en/data/products/"
            "auxiliary-products/global-tide-fes.html"
        ),
        "manual_note": (
            "FES2014 requires AVISO registration - no direct download URL.\n"
            "  1. Register at the link above.\n"
            "  2. Download per-constituent NetCDF files for M2, S2, K1, O1\n"
            "     (e.g. M2_ocean.nc, M2_load.nc, S2_ocean.nc, ...)\n"
            "  3. Place them at: data/fes2014/\n"
            "  4. Set config: tidal_forcing.source: fes2014"
        ),
    },
    "tpxo9": {
        "name": "TPXO9-atlas tidal constituents",
        "size_hint": "~4.1 GB (single multi-constituent NetCDF)",
        "dest": None,
        "manual_url": "https://www.tpxo.net/global/tpxo9-atlas",
        "manual_note": (
            "TPXO9-atlas requires registration on the TPXO portal.\n"
            "  1. Register and log in at the link above.\n"
            "  2. Download the grid file: h_tpxo9.v1.nc (~4.1 GB)\n"
            "  3. Place it at: data/tpxo9/h_tpxo9.v1.nc\n"
            "  4. Set config: tidal_forcing.source: tpxo9"
        ),
    },
}


# ---------------------------------------------------------------------------
# Download / extraction helpers
# ---------------------------------------------------------------------------


def _bar(progress: float, width: int = 30) -> str:
    filled = int(width * min(progress, 1.0))
    return f"[{'#' * filled}{'-' * (width - filled)}]"


def _report_hook(block_num: int, block_size: int, total_size: int):
    if total_size <= 0:
        return
    downloaded = block_num * block_size
    pct = min(downloaded / total_size, 1.0)
    mb_done = downloaded / 1e6
    mb_total = total_size / 1e6
    print(
        f"\r  {_bar(pct)} {pct * 100:5.1f}%  {mb_done:7.1f} / {mb_total:.1f} MB",
        end="",
        flush=True,
    )


def _download(url: str, dest: Path) -> bool:
    """Download a file with a progress bar. Returns True on success."""
    print(f"  -> {url}")
    try:
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        urlretrieve(url, dest, reporthook=_report_hook)
        print()
        size_mb = Path(dest).stat().st_size / 1e6
        print(f"  ok saved  {dest}  ({size_mb:.1f} MB)")
        return True
    except Exception as exc:
        print(f"\n  x failed: {exc}")
        if Path(dest).exists():
            Path(dest).unlink(missing_ok=True)
        return False


def _safe_member_path(extract_dir: Path, member: str) -> Path:
    """Resolve an archive member path safely inside *extract_dir*.

    Guards against zip-slip / path-traversal where a crafted archive contains
    members such as ``../evil.py`` or absolute paths that would escape the
    extraction directory.
    """
    member_path = Path(member)
    if member_path.is_absolute() or ".." in member_path.parts:
        raise ValueError(f"Unsafe archive member path: {member!r}")
    target = Path(extract_dir) / member_path
    extract_root = Path(extract_dir).resolve()
    try:
        target_resolved = target.resolve()
    except OSError:
        target_resolved = target
    if not str(target_resolved).startswith(str(extract_root)):
        raise ValueError(f"Archive member escapes extraction dir: {member!r}")
    return target


def _unzip(zip_path: Path, extract_dir: Path, flatten: bool = False):
    """Unzip a file into extract_dir (safe against path traversal)."""
    print(f"  -> extracting to {extract_dir}/")
    with zipfile.ZipFile(zip_path, "r") as zf:
        members = zf.namelist()
        for member in members:
            name = Path(member).name if flatten else member
            target = _safe_member_path(extract_dir, name)
            if member.endswith("/"):
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
    print(f"  ok extracted {len(members)} files")


def _untar(tar_path: Path, extract_dir: Path):
    """Extract a (possibly gzipped) tar into extract_dir (safe traversal)."""
    print(f"  -> extracting to {extract_dir}/")
    with tarfile.open(tar_path, "r:*") as tf:
        members = tf.getmembers()
        for member in members:
            _safe_member_path(extract_dir, member.name)
        tf.extractall(extract_dir)
    print(f"  ok extracted {len(members)} members")


def _untar_got(tar_path: Path, data_dir: Path):
    """Extract the GOT4.10c archive into data_dir (keeps GOT4.10c/ prefix)."""
    if not tar_path.exists():
        return
    got_dir = data_dir / "GOT4.10c"
    if got_dir.is_dir() and any(got_dir.iterdir()):
        print(f"  ok already extracted at {got_dir}/")
        return
    _untar(tar_path, data_dir)


def _fetch_gebco_subset(dest: Path, data_dir: Path) -> bool:
    """Read the Philippines window of the GEBCO COG and write a NetCDF subset.

    Uses rasterio range requests so only the region window (~17 MB) is
    transferred, not the 7.4 GB global grid.
    """
    import numpy as np
    import rasterio
    import xarray as xr
    from rasterio.windows import from_bounds

    b = PHILIPPINES_BBOX
    try:
        with rasterio.open(GEBCO_COG_URL) as src:
            win = from_bounds(
                b["lon_min"],
                b["lat_min"],
                b["lon_max"],
                b["lat_max"],
                transform=src.transform,
            )
            elev = src.read(1, window=win).astype(np.float32)[::-1, :]
            dlat, dlon = src.transform[4], src.transform[0]  # e = -dy, a = dx
            lat0 = src.transform.f + (win.row_off + 0.5) * dlat
            lon0 = src.transform.c + (win.col_off + 0.5) * dlon
    except Exception as exc:
        print(f"  x failed to read GEBCO subset: {exc}")
        return False

    ny, nx = elev.shape
    # Elevation rows run north->south after the read (flipped to south->north
    # above); emit ascending lat to match the official GEBCO subset convention.
    lat_south = lat0 + dlat * (ny - 1)
    lat = lat_south + (-dlat) * np.arange(ny)
    lon = lon0 + dlon * np.arange(nx)

    ds = xr.Dataset(
        {"elevation": (("lat", "lon"), elev)},
        coords={"lat": lat, "lon": lon},
        attrs={
            "title": "GEBCO_2026 Grid (Philippines subset)",
            "Conventions": "CF-1.6, ACDD-1.3",
            "comment": (
                "The data in the GEBCO_2026 Grid should not be used for "
                "navigation or any purpose relating to safety at sea."
            ),
            "source": (
                "GEBCO Bathymetric Compilation Group 2026. The GEBCO_2026 "
                "Grid, doi:10.5285/4f68d5c7-45eb-f999-e063-7086abc036fa"
            ),
            "license": "https://www.gebco.net/data_and_products/gridded_bathymetry_data/",
        },
    )
    ds["elevation"].attrs = {
        "long_name": "elevation (relative to sea level)",
        "units": "m",
        "positive": "up",
    }

    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        ds.to_netcdf(dest)
    except Exception as exc:
        print(f"  x failed to write NetCDF: {exc}")
        return False
    size_mb = dest.stat().st_size / 1e6
    print(f"  ok saved  {dest}  ({size_mb:.1f} MB)")
    return True


POST_PROCESSORS = {
    "untar_got": lambda p, d: _untar_got(p, d),
}

FETCHERS = {
    "gebco_subset": lambda dest, data_dir: _fetch_gebco_subset(dest, data_dir),
}


# ---------------------------------------------------------------------------
# Main download logic
# ---------------------------------------------------------------------------


def _post_output_present(ds: dict, data_dir: Path) -> bool:
    """Return True if the dataset's post-processed output already exists."""
    if ds.get("dest"):
        prefix = ds["dest"].rsplit(".", 1)[0]
        extract_dir = data_dir / prefix
        if extract_dir.is_dir() and any(extract_dir.iterdir()):
            return True
    if ds.get("post_process") == "untar_got":
        nc_dir = data_dir / "GOT4.10c" / "grids_oceantide_netcdf"
        return nc_dir.is_dir() and any(nc_dir.glob("*.nc"))
    return False


def download_dataset(
    key: str,
    data_dir: Path,
    *,
    skip_existing: bool = True,
) -> bool:
    """Acquire a single dataset. Returns True if present after the call."""
    ds = DATASETS[key]
    name = ds["name"]

    print(f"\n{'-' * 60}")
    print(f"  {name}")
    print(f"  Size: {ds['size_hint']}")
    print()

    dest_path = data_dir / ds["dest"] if ds["dest"] else None

    if dest_path and dest_path.exists() and skip_existing:
        size_mb = dest_path.stat().st_size / 1e6
        print(f"  ok already exists  {dest_path}  ({size_mb:.1f} MB)")
        _post_process(ds, data_dir)
        return True

    if _post_output_present(ds, data_dir):
        print("  ok already extracted")
        return True

    # --- Fetch ---
    ok = False
    if ds.get("fetcher"):
        ok = FETCHERS[ds["fetcher"]](dest_path, data_dir)
    elif ds.get("urls"):
        for url in ds["urls"]:
            if _download(url, dest_path):
                ok = True
                break
            print("  trying next source ...")
    else:
        print("  ! No direct download URL - requires manual steps.")
        print(f"\n  Manual URL: {ds['manual_url']}")
        print(f"  {ds['manual_note']}")
        return False

    if ok:
        _post_process(ds, data_dir)
    return ok


def _post_process(ds: dict, data_dir: Path):
    """Run post-processing (extraction) if configured and not already done."""
    if not ds.get("post_process"):
        return
    dest_path = data_dir / ds["dest"] if ds.get("dest") else None
    if dest_path is not None and not dest_path.exists():
        return
    POST_PROCESSORS[ds["post_process"]](dest_path, data_dir)


# ---------------------------------------------------------------------------
# Interactive prompts
# ---------------------------------------------------------------------------


def interactive(data_dir: Path):
    """Step through each dataset with y/N prompts."""
    print(
        "\n"
        "  Philippine Tidal Energy - Data Downloader\n"
        "  -----------------------------------------\n"
    )
    print(f"  Output directory: {data_dir.resolve()}\n")

    acquired = {}
    for key, ds in DATASETS.items():
        if ds.get("dest") is None:
            print(f"\n  {ds['name']} - manual download only.")
            choice = input("  Show instructions? [Y/n]: ").strip().lower()
            if choice in ("", "y"):
                print(f"\n  Manual URL: {ds['manual_url']}")
                print(f"  {ds['manual_note']}\n")
            acquired[key] = False
            continue

        choice = (
            input(f"  Download {ds['name']} ({ds['size_hint']})? [y/N]: ")
            .strip()
            .lower()
        )
        if choice == "y":
            acquired[key] = download_dataset(key, data_dir)
        else:
            print(f"\n  Skipped {ds['name']}.\n")
            acquired[key] = False

    _print_summary(acquired, data_dir)


def auto_all(data_dir: Path):
    """Download everything that can be automated."""
    print(
        "\n"
        "  Auto-downloading all datasets with direct URLs ...\n"
        f"  Output directory: {data_dir.resolve()}\n"
    )

    acquired = {}
    for key in DATASETS:
        acquired[key] = download_dataset(key, data_dir)

    _print_summary(acquired, data_dir)


def _print_summary(acquired: dict, data_dir: Path):
    print(f"\n{'-' * 60}")
    print("  Summary\n")
    for key, ok in acquired.items():
        ds = DATASETS[key]
        status = "ok" if ok else "x (see manual instructions above)"
        print(f"  {status:<8} {ds['name']}")

    print(f"\n  All downloads go to: {data_dir.resolve()}")
    print(
        "  src/model/config.yaml already points at these files:\n"
        "    bathymetry.path        -> data/GEBCO_28_Aug_2026_0bcab7925fa2/gebco_2026_*.nc\n"
        "    bathymetry.land_shapefile -> data/philippines_landmass.geojson\n"
        "    tidal_forcing.path     -> data/GOT4.10c/grids_oceantide_netcdf/\n"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Download external datasets for the Philippine tidal-energy workflow."
    )
    parser.add_argument(
        "--data-dir",
        default=os.path.join(os.path.dirname(__file__), "data"),
        help="Output directory (default: ./data)",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--all",
        action="store_true",
        help="Download all datasets that can be automated",
    )
    group.add_argument(
        "--gebco",
        action="store_true",
        help="Download the GEBCO 2026 bathymetry subset only",
    )
    group.add_argument(
        "--landmask",
        action="store_true",
        help="Download the Philippines landmass GeoJSON only",
    )
    group.add_argument(
        "--tidal",
        action="store_true",
        help="Download GOT4.10c and show manual steps for FES2014 + TPXO9",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download even if files already exist",
    )

    args = parser.parse_args()
    data_dir = Path(args.data_dir)
    skip_existing = not args.force

    if args.all:
        auto_all(data_dir)
    elif args.gebco:
        download_dataset("gebco", data_dir, skip_existing=skip_existing)
    elif args.landmask:
        download_dataset("landmask", data_dir, skip_existing=skip_existing)
    elif args.tidal:
        download_dataset("got", data_dir, skip_existing=skip_existing)
        for key in ("fes2014", "tpxo9"):
            ds = DATASETS[key]
            print(f"\n  {ds['name']}\n")
            print(f"  Manual URL: {ds['manual_url']}")
            print(f"  {ds['manual_note']}")
    else:
        interactive(data_dir)


if __name__ == "__main__":
    main()
