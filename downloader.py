#!/usr/bin/env python3
"""Download required external datasets for the Philippine tidal-energy workflow.

Datasets:
  GEBCO 2024          — global bathymetry (NetCDF, ~2.7 GB)
  Philippines OSM     — coastline / land-polygon shapefile from Geofabrik
  Philippines GADM    — admin-boundary shapefile from GADM
  FES2014 harmonics   — tidal constituent amplitude & phase (manual)

Usage:
  python downloader.py                  # guided interactive mode
  python downloader.py --all            # download everything that can be automated
  python downloader.py --gebco          # bathymetry only
  python downloader.py --shoreline      # OSM + GADM shapefiles only
  python downloader.py --data-dir ./data  # custom output directory
"""

from __future__ import annotations

import argparse
import os
import shutil
import zipfile
from pathlib import Path
from urllib.request import urlretrieve

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DATASETS: dict[str, dict] = {
    "gebco": {
        "name": "GEBCO 2026 bathymetry",
        "required": False,
        "size_hint": "~3.5 GB (global NetCDF)",
        "urls": [],
        "dest": "GEBCO_2026.nc",
        "post_process": None,
        "manual_url": "https://www.gebco.net/data_and_products/gridded_bathymetry_data/gebco_2024/",
        "manual_note": (
            "GEBCO requires accepting licence terms — no direct download URL.\n"
            "  1. Open the link above and fill in your details.\n"
            "  2. Download the global NetCDF: GEBCO_2024.nc (~2.7 GB)\n"
            "  3. Place it at: data/GEBCO_2024.nc\n"
            "  Without bathymetry the model still runs on a synthetic flat grid."
        ),
    },
    "osm_shoreline": {
        "name": "OSM Philippines shoreline (Geofabrik)",
        "required": False,
        "size_hint": "~25 MB (zipped)",
        "urls": [
            "https://download.geofabrik.de/asia/philippines-latest-free.shp.zip",
        ],
        "dest": "philippines-latest-free.shp.zip",
        "post_process": "unzip_osm",
        "manual_url": "https://download.geofabrik.de/asia/philippines.html",
        "manual_note": (
            "Download the .shp.zip from Geofabrik and place it in the data/ directory."
        ),
    },
    "gadm": {
        "name": "GADM Philippines admin boundary",
        "required": False,
        "size_hint": "~15 MB (zipped)",
        "urls": [
            "https://geodata.ucdavis.edu/gadm/gadm4.1/shp/gadm41_PHL_shp.zip",
        ],
        "dest": "gadm41_PHL_shp.zip",
        "post_process": "unzip",
        "manual_url": "https://gadm.org/download_country.html",
        "manual_note": (
            "Select Philippines → Shapefile → download gadm41_PHL_shp.zip.  "
            "Place it in the data/ directory."
        ),
    },
    "fes2014": {
        "name": "FES2014 tidal constituents",
        "required": False,
        "size_hint": "~2 GB (global per-constituent files)",
        "urls": [],
        "dest": None,
        "post_process": None,
        "manual_url": (
            "https://www.aviso.altimetry.fr/en/data/products/"
            "auxiliary-products/global-tide-fes.html"
        ),
        "manual_note": (
            "FES2014 requires AVISO registration — no direct download URL.\n"
            "  1. Register at the link above.\n"
            "  2. Download per-constituent NetCDF files for M2, S2, K1, O1\n"
            "     (e.g. M2_ocean.nc, M2_load.nc, S2_ocean.nc, ...)\n"
            "  3. Place them at: data/fes2014/\n"
            "  The model uses synthetic M2 forcing if these are absent."
        ),
    },
    "tpxo9": {
        "name": "TPXO9-atlas tidal constituents",
        "required": False,
        "size_hint": "~4.1 GB (single multi-constituent NetCDF)",
        "urls": [],
        "dest": None,
        "post_process": None,
        "manual_url": "https://www.tpxo.net/global/tpxo9-atlas",
        "manual_note": (
            "TPXO9-atlas requires registration on the TPXO portal.\n"
            "  1. Register and log in at the link above.\n"
            "  2. Download the grid file: h_tpxo9.v1.nc (~4.1 GB)\n"
            "  3. Place it at: data/tpxo9/h_tpxo9.v1.nc\n"
            "  4. Set config: tidal_forcing.source: tpxo9, path: data/tpxo9/h_tpxo9.v1.nc"
        ),
    },
    "got": {
        "name": "GOT4.10c tidal harmonics (NASA GSFC — no registration)",
        "required": False,
        "size_hint": "~44 MB (zipped tar)",
        "urls": [
            "https://earth.gsfc.nasa.gov/sites/default/files/2023-12/got4.10c.tar.gz",
        ],
        "dest": "got4.10c.tar.gz",
        "post_process": None,
        "manual_url": "https://earth.gsfc.nasa.gov/geo/data/ocean-tide-models",
        "manual_note": (
            "NASA Goddard Ocean Tide models are free — no registration required.\n"
            "  Download GOT4.10c (recommended) or GOT5.5 (~875 MB, higher res).\n"
            "  The data is in OTIS binary format; extract with tar xzf and\n"
            "  use OTPS (Fortran) or TMD (Matlab) to read harmonics.\n"
            "  NetCDF conversion may be needed before use with this model."
        ),
    },
}


# ---------------------------------------------------------------------------
# Helpers
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
    """Download a file with progress bar.  Returns True on success."""
    print(f"  → {url}")
    try:
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        urlretrieve(url, dest, reporthook=_report_hook)
        print()
        size_mb = Path(dest).stat().st_size / 1e6
        print(f"  ✓ saved  {dest}  ({size_mb:.1f} MB)")
        return True
    except Exception as exc:
        print(f"\n  ✗ failed: {exc}")
        if Path(dest).exists():
            Path(dest).unlink(missing_ok=True)
        return False


def _safe_member_path(extract_dir: Path, member: str) -> Path:
    """Resolve an archive member path safely inside *extract_dir*.

    Guards against zip-slip attacks where a crafted archive contains
    members such as ``../evil.py`` or absolute paths that would escape
    the extraction directory.
    """
    member_path = Path(member)
    if member_path.is_absolute() or ".." in member_path.parts:
        raise ValueError(f"Unsafe archive member path: {member!r}")
    target = Path(extract_dir) / member_path
    extract_root = Path(extract_dir).resolve()
    try:
        target_resolved = target.resolve()
    except OSError:
        # resolve() can fail on symlink loops etc.; fall back to parts check
        target_resolved = target
    if not str(target_resolved).startswith(str(extract_root)):
        raise ValueError(f"Archive member escapes extraction dir: {member!r}")
    return target


def _unzip(zip_path: Path, extract_dir: Path, flatten: bool = False):
    """Unzip a file into extract_dir (safe against path traversal)."""
    print(f"  → extracting to {extract_dir}/")
    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.namelist():
            target = (
                _safe_member_path(extract_dir, Path(member).name)
                if flatten
                else _safe_member_path(extract_dir, member)
            )
            if member.endswith("/"):
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
    print(f"  ✓ extracted {len(zf.namelist())} files")


def _unzip_osm(zip_path: Path, extract_dir: Path):
    """Unzip OSM shapefile — keep flat structure."""
    _unzip(zip_path, extract_dir, flatten=True)


POST_PROCESSORS = {
    "unzip": lambda p, d: _unzip(p, d),
    "unzip_osm": lambda p, d: _unzip_osm(p, d),
}


# ---------------------------------------------------------------------------
# Main download logic
# ---------------------------------------------------------------------------


def download_dataset(
    key: str,
    data_dir: Path,
    *,
    skip_existing: bool = True,
) -> bool:
    """Download a single dataset.  Returns True if acquired (or already present)."""
    ds = DATASETS[key]
    name = ds["name"]

    print(f"\n{'─' * 60}")
    print(f"  {name}")
    print(f"  Size: {ds['size_hint']}")
    if not ds["required"]:
        print("  (optional — model can run with synthetic/grid data)")
    print()

    dest_path = None
    if ds["dest"]:
        dest_path = data_dir / ds["dest"]

    # --- If already present ---
    if dest_path and dest_path.exists() and skip_existing:
        size_mb = dest_path.stat().st_size / 1e6
        print(f"  ✓ already exists  {dest_path}  ({size_mb:.1f} MB)")
        _post_process(ds, data_dir, dest_path)
        return True

    # Also check post-process output
    post = ds.get("post_process")
    if post and _post_process_present(ds, data_dir, dest_path, post):
        print("  ✓ already extracted")
        return True

    # --- Attempt auto-download ---
    urls = ds.get("urls", [])
    if urls:
        for url in urls:
            if dest_path and _download(url, dest_path):
                _post_process(ds, data_dir, dest_path)
                return True
            # try next mirror
            print("  trying next source …")
    else:
        print("  ⚠ No direct download URL — requires manual steps.")

    # --- Manual fallback ---
    print(f"\n  Manual URL: {ds['manual_url']}")
    print(f"  {ds['manual_note']}")
    return False


def _post_process_present(
    ds: dict, data_dir: Path, dest_path: Path | None, post: str
) -> bool:
    """Check if post-processed output already exists."""
    prefix = ds["dest"].rsplit(".", 1)[0] if ds["dest"] else ds.get("key", "")
    extract_dir = data_dir / prefix
    return extract_dir.is_dir() and any(extract_dir.iterdir())


def _post_process(ds: dict, data_dir: Path, dest_path: Path | None):
    """Run post-processing (unzip etc.) if configured and not already done."""
    if dest_path is None or not dest_path.exists():
        return
    post = ds.get("post_process")
    if not post:
        return
    prefix = ds["dest"].rsplit(".", 1)[0]
    extract_dir = data_dir / prefix
    if extract_dir.is_dir() and any(extract_dir.iterdir()):
        return
    extract_dir.mkdir(parents=True, exist_ok=True)
    POST_PROCESSORS[post](dest_path, extract_dir)


# ---------------------------------------------------------------------------
# Interactive prompts
# ---------------------------------------------------------------------------


def interactive(data_dir: Path):
    """Step through each dataset with y/N prompts."""
    print(
        "\n"
        "  Philippine Tidal Energy — Data Downloader\n"
        "  ─────────────────────────────────────────\n"
    )
    print(f"  Output directory: {data_dir.resolve()}\n")

    acquired = {}
    for key, ds in DATASETS.items():
        req = "required" if ds["required"] else "optional"
        if ds["urls"]:
            choice = (
                input(f"  Download {ds['name']} ({req}, {ds['size_hint']})? [y/N]: ")
                .strip()
                .lower()
            )
        else:
            print(f"\n  {ds['name']} ({req}) — manual download only.")
            choice = input("  Show instructions? [Y/n]: ").strip().lower()
            if choice == "" or choice == "y":
                print(f"\n  Manual URL: {ds['manual_url']}")
                print(f"  {ds['manual_note']}\n")
            acquired[key] = False
            continue

        if choice == "y":
            acquired[key] = download_dataset(key, data_dir)
        else:
            print(f"\n  Skipped {ds['name']}.\n")
            acquired[key] = False

    _print_summary(acquired, data_dir)


def auto_all(data_dir: Path):
    """Download everything that has direct URLs."""
    print(
        "\n"
        "  Auto-downloading all datasets with direct URLs …\n"
        f"  Output directory: {data_dir.resolve()}\n"
    )

    acquired = {}
    for key in DATASETS:
        acquired[key] = download_dataset(key, data_dir)

    _print_summary(acquired, data_dir)


def _print_summary(acquired: dict, data_dir: Path):
    print(f"\n{'─' * 60}")
    print("  Summary\n")
    for key, ok in acquired.items():
        ds = DATASETS[key]
        status = "✓" if ok else "✗ (see manual instructions above)"
        print(f"  {status}  {ds['name']}")

    print(f"\n  All downloads go to: {data_dir.resolve()}")
    print(
        "  Update src/model/config.yaml to point bathymetry.path, "
        "tidal_forcing.path, and land_shapefile to these locations.\n"
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
        help="Download all datasets that have direct URLs",
    )
    group.add_argument(
        "--gebco",
        action="store_true",
        help="Download GEBCO 2024 bathymetry only",
    )
    group.add_argument(
        "--shoreline",
        action="store_true",
        help="Download OSM + GADM shapefiles only",
    )
    group.add_argument(
        "--tidal",
        action="store_true",
        help="Show manual download instructions for FES2014 + TPXO9",
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
    elif args.shoreline:
        download_dataset("osm_shoreline", data_dir, skip_existing=skip_existing)
        download_dataset("gadm", data_dir, skip_existing=skip_existing)
    elif args.tidal:
        for key in ("fes2014", "tpxo9", "got"):
            ds = DATASETS[key]
            print(f"\n  {ds['name']}\n")
            print(f"  Manual URL: {ds['manual_url']}")
            print(f"  {ds['manual_note']}")
        print(
            "\n  FES2014 directory structure:\n"
            "    data/fes2014/\n"
            "      M2_ocean.nc    M2_load.nc\n"
            "      S2_ocean.nc    S2_load.nc\n"
            "      K1_ocean.nc    K1_load.nc\n"
            "      O1_ocean.nc    O1_load.nc\n"
            "\n  TPXO9 file placement:\n"
            "    data/tpxo9/h_tpxo9.v1.nc\n"
            "\n  GOT4.10c file placement:\n"
            "    data/got4.10c.tar.gz  (auto-extract with: tar xzf)\n"
        )
    else:
        interactive(data_dir)


if __name__ == "__main__":
    main()
