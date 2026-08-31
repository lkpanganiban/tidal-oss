#!/usr/bin/env python3
"""Generate synthetic test data for the tidal web service.

Produces a Cloud-Optimised GeoTIFF with realistic-looking tidal power-density
patterns across the Philippine archipelago, plus a GeoJSON hotspot layer.
No model run required — use this to verify the web map renders correctly.

Usage:
    python scripts/generate_test_data.py [--output-dir output/] [--resolution-km 2.0]

Writers are reused from ``src/model`` (``write_raster_geotiff``,
``distance_to_coast_km``, ``write_hotspots_geojson``) so the synthetic outputs
match the canonical model contract exactly.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import numpy as np

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from model.grid import StructuredGrid, distance_to_coast_km  # noqa: E402
from model.output import write_hotspots_geojson, write_raster_geotiff  # noqa: E402

# Approximate land grid for the Philippines at ~0.5° resolution (OK for test data).
# Values: 1 = water, 0 = land.  Crude — just enough to mask major islands.
# fmt: off
_LAND_TEMPLATE = np.array(
    [
        # each row = 0.5° lat  (4.0 → 22.0 N, 37 rows)
        # each col = 0.5° lon  (116.0 → 130.0 E, 28 cols)
        # 1=water, 0=land
        [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
        [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
        [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
        [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
        [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
        [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
        [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
        [1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
        [1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1],
        [1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1],
        [1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1],
        [1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1],
        [1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
        [1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1],
        [1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1],
        [1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1],
        [1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1],
        [1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1],
        [1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1],
        [1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1],
        [1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1],
        [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1],
        [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1],
        [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1],
        [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1],
        [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1],
        [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1],
        [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1],
        [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1],
        [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1],
        [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1],
        [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1],
        [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1],
        [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 1, 1, 1],
        [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 1, 1, 1],
        [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
        [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
    ],
    dtype=np.float32,
)
# fmt: on

# Map of key Philippine tidal straits: (lat, lon, peak_Wm2, sigma_deg)
_HOTSPOTS = [
    ("San Bernardino Strait", 12.5, 124.1, 1800, 0.6),
    ("Surigao Strait", 10.0, 125.5, 1500, 0.5),
    ("Verde Island Passage", 13.5, 120.9, 1200, 0.5),
    ("Balintang Channel", 19.8, 121.4, 1100, 0.6),
    ("Basilan Strait", 6.8, 122.0, 900, 0.4),
    ("Mindoro Strait", 12.3, 120.5, 1000, 0.5),
    ("Babuyan Channel", 18.7, 121.5, 800, 0.5),
    ("Luzon Strait (west)", 20.0, 121.0, 700, 0.8),
    ("Luzon Strait (east)", 20.5, 122.5, 600, 0.7),
    ("Mindanao Current zone", 7.0, 127.0, 500, 1.0),
    ("Panay Gulf", 10.5, 122.0, 400, 0.6),
    ("Palawan Passage", 9.0, 118.5, 350, 0.8),
]


def _gaussian(
    xx: np.ndarray, yy: np.ndarray, cx: float, cy: float, sx: float, sy: float
) -> np.ndarray:
    """2D Gaussian blob."""
    return np.exp(-((xx - cx) ** 2) / (2 * sx**2) - ((yy - cy) ** 2) / (2 * sy**2))


def _land_mask_at(lons: np.ndarray, lats: np.ndarray) -> np.ndarray:
    """Resample the coarse land template onto a lon/lat mesh.

    Returns a float array with 1 = water, 0 = land (matches the template
    convention).  Shape (len(lats), len(lons)).
    """
    lon_grid, lat_grid = np.meshgrid(lons, lats)

    land_lat_edges = np.linspace(lats.max(), lats.min(), _LAND_TEMPLATE.shape[0] + 1)
    land_lon_edges = np.linspace(lons.min(), lons.max(), _LAND_TEMPLATE.shape[1] + 1)

    land_mask = np.zeros((len(lats), len(lons)), dtype=np.float32)
    for j in range(len(lats)):
        lat_idx = (
            np.searchsorted(-land_lat_edges, -lat_grid[j, 0]) - 1
        )  # descending lat
        lat_idx = max(0, min(_LAND_TEMPLATE.shape[0] - 1, lat_idx))
        for i in range(len(lons)):
            lon_idx = np.searchsorted(land_lon_edges, lon_grid[j, i]) - 1
            lon_idx = max(0, min(_LAND_TEMPLATE.shape[1] - 1, lon_idx))
            land_mask[j, i] = _LAND_TEMPLATE[lat_idx, lon_idx]
    return land_mask


def _grid_setup(
    lon_min: float,
    lon_max: float,
    lat_min: float,
    lat_max: float,
    resolution_km: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return (lons, lats, lon_grid, lat_grid, water_mask)."""
    km_per_deg = 111.32
    dx = resolution_km / km_per_deg
    dy = resolution_km / km_per_deg

    nx = int((lon_max - lon_min) / dx) + 1
    ny = int((lat_max - lat_min) / dy) + 1

    lons = np.linspace(lon_min, lon_max, nx)
    lats = np.linspace(lat_min, lat_max, ny)
    lon_grid, lat_grid = np.meshgrid(lons, lats)
    water = _land_mask_at(lons, lats)
    return lons, lats, lon_grid, lat_grid, water


def _make_grid(
    lons: np.ndarray, lats: np.ndarray, water: np.ndarray, resolution_km: float
) -> StructuredGrid:
    """Wrap the synthetic domain in a StructuredGrid the model writers accept."""
    ny, nx = water.shape
    grid = StructuredGrid.from_uniform(
        nx=nx, ny=ny, dx=resolution_km * 1000.0, dy=resolution_km * 1000.0, lat0=0.0
    )
    lon2d, lat2d = np.meshgrid(lons, lats)
    grid.lon = lon2d
    grid.lat = lat2d
    grid.mask = water > 0.5
    grid.h = np.zeros((ny, nx), dtype=np.float64)
    return grid


def generate_geotiff(
    grid: StructuredGrid,
    water: np.ndarray,
    lon_grid: np.ndarray,
    lat_grid: np.ndarray,
    output_path: str,
    resolution_km: float,
    seed: int = 42,
) -> np.ndarray:
    """Generate a synthetic tidal-power-density COG GeoTIFF.

    Creates hotspot-like patterns near known Philippine tidal straits,
    masks out major land areas, and adds perlin-like noise.
    """
    rng = np.random.default_rng(seed)
    ny, nx = water.shape

    print(f"  Grid: {ny} rows x {nx} cols  ({resolution_km} km resolution)")
    print(
        f"  Domain: {grid.lon.min()}–{grid.lon.max()}°E, "
        f"{grid.lat.min()}–{grid.lat.max()}°N"
    )

    # --- Synthetic power density ---
    power = np.zeros((ny, nx), dtype=np.float32)
    for _name, lat, lon, peak, sigma in _HOTSPOTS:
        blob = _gaussian(lon_grid, lat_grid, lon, lat, sigma, sigma)
        power += blob * peak

    # Add structured noise (multi-scale for more realism)
    noise = np.zeros_like(power)
    for scale in [3.0, 1.5, 0.8]:
        coarse_ny = max(2, int(ny * scale / 20))
        coarse_nx = max(2, int(nx * scale / 20))
        coarse = rng.uniform(0.3, 1.0, (coarse_ny, coarse_nx))
        # bilinear-upsample to full resolution
        from scipy.ndimage import zoom

        up = zoom(coarse, (ny / coarse_ny, nx / coarse_nx), order=1)
        up = up[:ny, :nx]  # trim any rounding overflow
        noise += up * 100 * scale

    power += noise

    # Smooth transitions and apply mask
    from scipy.ndimage import gaussian_filter

    power = gaussian_filter(power, sigma=1.0)

    # Apply land mask — set land cells to nodata
    power[water < 0.5] = -9999.0

    write_raster_geotiff(
        grid,
        power,
        output_path,
        "mean tidal-current power density (W/m2)",
        nodata=-9999.0,
    )

    size_mb = os.path.getsize(output_path) / 1e6
    print(f"  ✓ written {output_path}  ({size_mb:.1f} MB)")

    # Print stats
    valid = power[water > 0.5]
    print(
        f"  Stats (water cells): min={valid.min():.0f}  max={valid.max():.0f}  "
        f"mean={valid.mean():.0f}  p95={np.percentile(valid, 95):.0f} W/m²"
    )
    return power


def generate_speed_geotiff(
    grid: StructuredGrid, power: np.ndarray, output_path: str, nodata: float = -9999.0
) -> None:
    """Derive a max-current-speed layer from the power GeoTIFF: U=(2P/ρ)^⅓."""
    rho = 1025.0
    speed = np.zeros_like(power, dtype=np.float64)
    pos = power > 0
    speed[pos] = (2.0 * power[pos] / rho) ** (1.0 / 3.0)
    if nodata is not None:
        speed[np.isclose(power, nodata)] = nodata

    write_raster_geotiff(
        grid,
        speed.astype(np.float32),
        output_path,
        "maximum depth-averaged current speed (m/s)",
        nodata=nodata,
    )
    print(f"  ✓ written {output_path}")


def generate_bathymetry_geotiff(
    grid: StructuredGrid,
    water: np.ndarray,
    lon_grid: np.ndarray,
    lat_grid: np.ndarray,
    output_path: str,
    resolution_km: float,
    seed: int = 42,
) -> None:
    """Synthetic bathymetry: shallow near coast, deepening offshore."""
    rng = np.random.default_rng(seed + 1)
    ny, nx = water.shape

    from scipy.ndimage import distance_transform_edt, gaussian_filter

    # scipy EDT: foreground (water) pixels report distance to nearest
    # background (land) pixel.
    dist_km = distance_transform_edt(water, sampling=(resolution_km, resolution_km))

    # Base depth grows with distance from land; straits (hotspots) are shallower.
    depth = 25.0 + 6.0 * dist_km
    for _name, lat, lon, _peak, sigma in _HOTSPOTS:
        blob = _gaussian(lon_grid, lat_grid, lon, lat, sigma * 2.0, sigma * 2.0)
        depth -= blob * 60.0  # shallower near straits
    depth += rng.uniform(-8, 8, (ny, nx))
    depth = gaussian_filter(depth, sigma=1.0)
    depth = np.clip(depth, 5.0, 4000.0)
    depth[water < 0.5] = -9999.0

    write_raster_geotiff(
        grid,
        depth.astype(np.float32),
        output_path,
        "bathymetric depth (m, positive down)",
        nodata=-9999.0,
    )
    print(f"  ✓ written {output_path}")


def generate_distance_geotiff(
    grid: StructuredGrid, output_path: str, nodata: float = -9999.0
) -> None:
    """Distance from every cell to the nearest coast [km]."""
    dist_km = distance_to_coast_km(grid.mask, grid.dx, grid.dy).astype(np.float32)
    dist_km[~grid.mask] = nodata

    write_raster_geotiff(
        grid,
        dist_km,
        output_path,
        "distance to nearest coast (km)",
        nodata=nodata,
    )
    print(f"  ✓ written {output_path}")


def generate_hotspots_geojson(
    grid: StructuredGrid, power: np.ndarray, output_path: str, threshold: float = 200.0
) -> None:
    """Extract hotspot points from the power field and write as GeoJSON."""
    write_hotspots_geojson(grid, power, threshold, output_path)

    print(f"  ✓ written {output_path}  (hotspots above {threshold} W/m²)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Generate synthetic test data for the tidal web service."
    )
    parser.add_argument(
        "--output-dir",
        default="output",
        help="Output directory (default: output/)",
    )
    parser.add_argument(
        "--resolution-km",
        type=float,
        default=2.0,
        help="Grid cell size in km (default: 2.0)",
    )
    parser.add_argument(
        "--hotspot-threshold",
        type=float,
        default=200.0,
        help="Minimum W/m² for hotspot GeoJSON (default: 200)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducible noise (default: 42)",
    )

    args = parser.parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    geotiff_path = str(output_dir / "tidal_power_density.tif")
    speed_path = str(output_dir / "max_current_speed.tif")
    bathy_path = str(output_dir / "bathymetry.tif")
    dist_path = str(output_dir / "distance_to_coast.tif")
    geojson_path = str(output_dir / "hotspots.geojson")

    print("\n  Tidal Web Service — Test Data Generator\n")
    print(f"  Output directory: {output_dir.resolve()}\n")

    lons, lats, lon_grid, lat_grid, water = _grid_setup(
        116.0, 130.0, 4.0, 22.0, args.resolution_km
    )
    grid = _make_grid(lons, lats, water, args.resolution_km)

    print("  [1/5] Generating power-density GeoTIFF …")
    power = generate_geotiff(
        grid,
        water,
        lon_grid,
        lat_grid,
        geotiff_path,
        args.resolution_km,
        seed=args.seed,
    )

    print("  [2/5] Deriving max-current-speed GeoTIFF …")
    generate_speed_geotiff(grid, power, speed_path)

    print("  [3/5] Generating bathymetry GeoTIFF …")
    generate_bathymetry_geotiff(
        grid, water, lon_grid, lat_grid, bathy_path, args.resolution_km, seed=args.seed
    )

    print("  [4/5] Generating distance-to-coast GeoTIFF …")
    generate_distance_geotiff(grid, dist_path)

    print("\n  [5/5] Extracting hotspots …")
    generate_hotspots_geojson(grid, power, geojson_path, args.hotspot_threshold)

    print("\n  Done. Start the web service with:")
    print(f"    GEOTIFF_PATH={geotiff_path} python -m src.web.app\n")


if __name__ == "__main__":
    main()
