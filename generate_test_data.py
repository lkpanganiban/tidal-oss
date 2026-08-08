#!/usr/bin/env python3
"""Generate synthetic test data for the tidal web service.

Produces a Cloud-Optimised GeoTIFF with realistic-looking tidal power-density
patterns across the Philippine archipelago, plus a GeoJSON hotspot layer.
No model run required — use this to verify the web map renders correctly.

Usage:
    python generate_test_data.py [--output-dir output/] [--resolution-km 2.0]
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np

# Approximate land grid for the Philippines at ~0.5° resolution (OK for test data).
# Values: 1 = water, 0 = land.  Crude — just enough to mask major islands.
_LAND_TEMPLATE = np.array(
    [
        # each row = 0.5° lat  (4.0 → 22.0 N, 36 rows)
        # each col = 0.5° lon  (116.0 → 130.0 E, 28 cols)
        # 1=water, 0=land
        [
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
        ],  # 22.0
        [
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
        ],  # 21.5
        [
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
        ],  # 21.0
        [
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
        ],  # 20.5
        [
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            0,
            0,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
        ],  # 20.0 (N.Luzon)
        [
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            0,
            0,
            0,
            0,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
        ],  # 19.5
        [
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
        ],  # 19.0
        [
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
        ],  # 18.5
        [
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
        ],  # 18.0 (Luzon)
        [
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
        ],  # 17.5
        [
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
        ],  # 17.0
        [
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
        ],  # 16.5
        [
            1,
            1,
            1,
            1,
            1,
            1,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
        ],  # 16.0
        [
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
        ],  # 15.5
        [
            1,
            1,
            1,
            1,
            1,
            1,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
        ],  # 15.0 (S.Luzon)
        [
            1,
            1,
            1,
            1,
            1,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
        ],  # 14.5
        [
            1,
            1,
            1,
            1,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
        ],  # 14.0 (Manila)
        [
            1,
            1,
            1,
            1,
            1,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
        ],  # 13.5 (Verde Is.)
        [
            1,
            1,
            1,
            1,
            1,
            1,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
        ],  # 13.0
        [
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
        ],  # 12.5 (S.Bernardino)
        [
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
        ],  # 12.0
        [
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            1,
            1,
            1,
            1,
            1,
            1,
        ],  # 11.5 (Samar)
        [
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            1,
            1,
            1,
            1,
            1,
            1,
        ],  # 11.0
        [
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
        ],  # 10.5 (Surigao)
        [
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            1,
            1,
            1,
            1,
            1,
            1,
        ],  # 10.0
        [
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            1,
            1,
            1,
            1,
            1,
            1,
        ],  # 9.5
        [
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            1,
            1,
            1,
            1,
            1,
        ],  # 9.0 (Mindanao)
        [
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            1,
            1,
            1,
            1,
        ],  # 8.5
        [
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            1,
            1,
            1,
        ],  # 8.0
        [
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            1,
            1,
        ],  # 7.5
        [
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            1,
        ],  # 7.0
        [
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            1,
            1,
        ],  # 6.5 (Basilan)
        [
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            1,
            1,
        ],  # 6.0
        [
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            0,
            0,
            0,
            0,
            0,
            0,
            1,
            1,
            1,
        ],  # 5.5
        [
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            0,
            0,
            0,
            0,
            0,
            1,
            1,
            1,
        ],  # 5.0
        [
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
        ],  # 4.5
        [
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
            1,
        ],  # 4.0
    ],
    dtype=np.float32,
)

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


def generate_geotiff(
    output_path: str,
    lon_min: float = 116.0,
    lon_max: float = 130.0,
    lat_min: float = 4.0,
    lat_max: float = 22.0,
    resolution_km: float = 2.0,
    seed: int = 42,
) -> None:
    """Generate a synthetic tidal-power-density COG GeoTIFF.

    Creates hotspot-like patterns near known Philippine tidal straits,
    masks out major land areas, and adds perlin-like noise.
    """
    import rasterio
    from rasterio.transform import from_bounds

    rng = np.random.default_rng(seed)

    # Grid dimensions
    km_per_deg = 111.32
    dx = resolution_km / km_per_deg
    dy = resolution_km / km_per_deg

    nx = int((lon_max - lon_min) / dx) + 1
    ny = int((lat_max - lat_min) / dy) + 1

    print(f"  Grid: {ny} rows x {nx} cols  ({resolution_km} km resolution)")
    print(f"  Domain: {lon_min}–{lon_max}°E, {lat_min}–{lat_max}°N")

    # Coordinate arrays (cell centres)
    lons = np.linspace(lon_min, lon_max, nx)
    lats = np.linspace(lat_min, lat_max, ny)
    lon_grid, lat_grid = np.meshgrid(lons, lats)

    # --- Land mask ---
    land_lat_edges = np.linspace(lat_max, lat_min, _LAND_TEMPLATE.shape[0] + 1)
    land_lon_edges = np.linspace(lon_min, lon_max, _LAND_TEMPLATE.shape[1] + 1)

    land_mask = np.zeros((ny, nx), dtype=np.float32)
    for j in range(ny):
        lat_idx = (
            np.searchsorted(-land_lat_edges, -lat_grid[j, 0]) - 1
        )  # descending lat
        lat_idx = max(0, min(_LAND_TEMPLATE.shape[0] - 1, lat_idx))
        for i in range(nx):
            lon_idx = np.searchsorted(land_lon_edges, lon_grid[j, i]) - 1
            lon_idx = max(0, min(_LAND_TEMPLATE.shape[1] - 1, lon_idx))
            land_mask[j, i] = _LAND_TEMPLATE[lat_idx, lon_idx]

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
    power[land_mask < 0.5] = -9999.0
    nodata = -9999.0

    # --- Write GeoTIFF ---
    transform = from_bounds(lon_min, lat_min, lon_max, lat_max, nx, ny)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    with rasterio.open(
        output_path,
        "w",
        driver="COG",
        height=ny,
        width=nx,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=transform,
        nodata=nodata,
        TILING_SCHEME="GoogleMapsCompatible",
        COMPRESS="LZW",
    ) as dst:
        dst.write(power.astype(np.float32), 1)
        dst.set_band_description(1, "mean tidal-current power density (W/m2)")

    size_mb = os.path.getsize(output_path) / 1e6
    print(f"  ✓ written {output_path}  ({size_mb:.1f} MB)")

    # Print stats
    valid = power[land_mask > 0.5]
    print(
        f"  Stats (water cells): min={valid.min():.0f}  max={valid.max():.0f}  "
        f"mean={valid.mean():.0f}  p95={np.percentile(valid, 95):.0f} W/m²"
    )


def generate_hotspots_geojson(
    geotiff_path: str,
    output_path: str,
    threshold: float = 200.0,
) -> None:
    """Extract hotspot points from the GeoTIFF and write as GeoJSON."""
    import rasterio

    with rasterio.open(geotiff_path) as src:
        data = src.read(1)
        nodata = src.nodata
        transform = src.transform
        src_crs = src.crs

    if nodata is not None:
        mask = ~(np.isclose(data, nodata) | np.isnan(data))
    else:
        mask = ~np.isnan(data)

    rows, cols = np.where(mask & (data > threshold))
    xs, ys = rasterio.transform.xy(transform, rows, cols)

    # Convert to EPSG:4326 if the GeoTIFF was reprojected by the COG driver
    if src_crs is not None and src_crs.to_epsg() != 4326:
        from rasterio.warp import transform as reproject_coords

        lons, lats = reproject_coords(src_crs, "EPSG:4326", xs, ys)
    else:
        lons, lats = xs, ys

    features = []
    for i in range(len(rows)):
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lons[i], lats[i]]},
                "properties": {
                    "power_density_Wm2": round(float(data[rows[i], cols[i]]), 1)
                },
            }
        )

    geojson = {"type": "FeatureCollection", "features": features}
    with open(output_path, "w") as f:
        json.dump(geojson, f, indent=2)

    print(
        f"  ✓ written {output_path}  ({len(features)} hotspots above {threshold} W/m²)"
    )


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
    geojson_path = str(output_dir / "hotspots.geojson")

    print("\n  Tidal Web Service — Test Data Generator\n")
    print(f"  Output directory: {output_dir.resolve()}\n")

    print("  [1/2] Generating GeoTIFF …")
    generate_geotiff(
        geotiff_path,
        resolution_km=args.resolution_km,
        seed=args.seed,
    )

    print("\n  [2/2] Extracting hotspots …")
    generate_hotspots_geojson(
        geotiff_path,
        geojson_path,
        threshold=args.hotspot_threshold,
    )

    print("\n  Done. Start the web service with:")
    print(f"    GEOTIFF_PATH={geotiff_path} python -m src.web.app\n")


if __name__ == "__main__":
    main()
