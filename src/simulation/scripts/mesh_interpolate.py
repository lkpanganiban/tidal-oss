#!/usr/bin/env python3
"""
Interpolate GEBCO bathymetry raster onto unstructured mesh nodes.

Inputs:
  - Gmsh mesh file (.msh)
  - GEBCO bathymetry GeoTIFF (clipped to AOI, positive depths, land=NoData)

Output:
  - CSV file with depth (m, positive down) at each mesh node
"""

import argparse
import sys
from pathlib import Path

import numpy as np

try:
    import meshio
except ImportError:
    print("ERROR: meshio not found. Install with: pip install meshio")
    sys.exit(1)

try:
    import rioxarray
except ImportError:
    print("ERROR: rioxarray not found. Install with: pip install rioxarray")
    sys.exit(1)

try:
    from scipy.interpolate import RegularGridInterpolator
except ImportError:
    print("ERROR: scipy not found. Install with: pip install scipy")
    sys.exit(1)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Interpolate GEBCO bathymetry onto mesh nodes"
    )
    parser.add_argument(
        "--mesh", type=str, required=True,
        help="Path to Gmsh .msh file"
    )
    parser.add_argument(
        "--gebco", type=str, required=True,
        help="Path to GEBCO GeoTIFF (clipped, with positive depths)"
    )
    parser.add_argument(
        "--output", type=str, default="bathymetry.csv",
        help="Output CSV path (default: bathymetry.csv)"
    )
    parser.add_argument(
        "--min-depth", type=float, default=2.0,
        help="Minimum depth in meters (default: 2.0)"
    )
    return parser.parse_args()


def interpolate_bathymetry(mesh_path: str, gebco_path: str, min_depth: float = 2.0):
    """Interpolate GEBCO depths onto mesh nodes."""
    print(f"Reading mesh from {mesh_path}...")
    mesh = meshio.read(mesh_path)
    nodes = mesh.points[:, :2]  # (lon, lat)

    print(f"  Mesh nodes: {len(nodes)}")

    print(f"Reading bathymetry from {gebco_path}...")
    bathy = rioxarray.open_rasterio(gebco_path).squeeze()

    # GEBCO values: negative = below sea level, positive = above
    # We want positive = depth, so flip sign
    depths_raster = -bathy.values

    # Handle NoData: replace with a large value then clamp
    nodata = bathy.rio.nodata
    if nodata is not None:
        depths_raster = np.where(bathy.values == nodata, np.nan, depths_raster)

    print(f"  Raster shape: {depths_raster.shape}")
    print(f"  Raster extent: lon=[{bathy.x.values[0]:.2f}, {bathy.x.values[-1]:.2f}], "
          f"lat=[{bathy.y.values[0]:.2f}, {bathy.y.values[-1]:.2f}]")

    # Build interpolator (note: rioxarray y is decreasing)
    y = bathy.y.values  # decreasing (north → south)
    x = bathy.x.values  # increasing (west → east)
    depths = depths_raster  # [y, x]

    interp = RegularGridInterpolator(
        (y[::-1], x),  # flip y to increasing
        depths[::-1, :],  # flip rows accordingly
        bounds_error=False,
        fill_value=np.nan,
    )

    # Interpolate: nodes are (lon, lat), interp expects (lat, lon)
    node_depths = interp(nodes[:, ::-1])

    # Fill NaNs (outside raster) with a default depth
    nan_mask = np.isnan(node_depths)
    if nan_mask.any():
        print(f"  {nan_mask.sum()} nodes outside bathymetry extent — assigning min depth")
        node_depths[nan_mask] = min_depth

    # Enforce minimum depth
    node_depths = np.maximum(node_depths, min_depth)

    return node_depths


def main():
    args = parse_args()

    mesh_path = Path(args.mesh)
    gebco_path = Path(args.gebco)

    if not mesh_path.exists():
        print(f"ERROR: Mesh file not found: {args.mesh}")
        sys.exit(1)
    if not gebco_path.exists():
        print(f"ERROR: GEBCO raster not found: {args.gebco}")
        sys.exit(1)

    depths = interpolate_bathymetry(
        args.mesh, args.gebco, args.min_depth
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    np.savetxt(output_path, depths, delimiter=",", fmt="%.2f")

    print(f"Bathymetry written to {args.output}")
    print(f"  Depth range: {depths.min():.1f} – {depths.max():.1f} m")
    print(f"  Mean depth: {depths.mean():.1f} m")


if __name__ == "__main__":
    main()
