#!/usr/bin/env python3
"""
Post-process Thetis HDF5 simulation output:
  1. Read velocity time-series from HDF5 files
  2. Compute depth-averaged tidal-current power density: P = 0.5 * ρ * U³
  3. Time-average over the simulation period
  4. Rasterize onto a regular grid → Cloud-Optimized GeoTIFF (COG)

Input:
  - Thetis HDF5 output directory (containing hdf5/*.h5 files)
  - Gmsh mesh file (for node coordinates, optional)

Output:
  - Cloud-Optimized GeoTIFF of time-averaged power density (W/m²)
"""

import argparse
import sys
from pathlib import Path

import numpy as np

try:
    import h5py
except ImportError:
    print("ERROR: h5py not found. Install with: pip install h5py")
    sys.exit(1)

try:
    from scipy.interpolate import griddata
except ImportError:
    print("ERROR: scipy not found. Install with: pip install scipy")
    sys.exit(1)


SEAWATER_DENSITY = 1025.0  # kg/m³


def parse_args():
    parser = argparse.ArgumentParser(
        description="Post-process Thetis output to tidal power density COG"
    )
    parser.add_argument(
        "--input", type=str, required=True,
        help="Path to Thetis output directory (contains hdf5/ subdir)"
    )
    parser.add_argument(
        "--mesh", type=str, default=None,
        help="Path to Gmsh .msh file for node coordinates (optional — auto-detected from HDF5)"
    )
    parser.add_argument(
        "--output", type=str, default="tidal_power_density.tif",
        help="Output GeoTIFF path (default: tidal_power_density.tif)"
    )
    parser.add_argument(
        "--resolution", type=float, default=500,
        help="Output pixel resolution in meters (default: 500)"
    )
    parser.add_argument(
        "--start-day", type=float, default=2,
        help="Spin-up days to discard (default: 2)"
    )
    return parser.parse_args()


def read_thetis_hdf5(input_dir: str, start_day: float):
    """Read velocity time-series from Thetis HDF5 output."""
    hdf5_dir = Path(input_dir) / "hdf5"
    if not hdf5_dir.exists():
        vfiles = sorted(Path(input_dir).glob("Velocity2d_*.h5"))
        if not vfiles:
            vfiles = sorted(Path(input_dir).glob("uv_2d_*.h5"))
        if not vfiles:
            raise FileNotFoundError(
                f"No HDF5 velocity files found in {input_dir} or {hdf5_dir}"
            )
    else:
        vfiles = sorted(hdf5_dir.glob("Velocity2d_*.h5"))
        if not vfiles:
            vfiles = sorted(hdf5_dir.glob("uv_2d_*.h5"))

    if not vfiles:
        raise FileNotFoundError(f"No velocity HDF5 files found")

    print(f"Found {len(vfiles)} velocity HDF5 files")

    all_times = []
    for vf in vfiles:
        with h5py.File(vf, "r") as f:
            if "time" in f:
                all_times.append(float(f["time"][()]))

    if all_times:
        print(f"  Time range: {min(all_times):.1f} – {max(all_times):.1f} s")
        print(f"  ({min(all_times) / 3600:.1f} – {max(all_times) / 3600:.1f} h)")

    start_time = start_day * 24 * 3600
    n_nodes = None
    power_sum = None
    count = 0

    for vf in vfiles:
        with h5py.File(vf, "r") as f:
            file_time = float(f["time"][()]) if "time" in f else 0.0
            if file_time < start_time:
                continue

            u = None
            v = None

            for key in f.keys():
                if key == "time":
                    continue
                group = f[key]
                for fname in group.keys():
                    data = group[fname][:]
                    data = np.array(data).ravel()
                    if u is None:
                        u = data
                    elif v is None:
                        v = data
                        break

            if u is not None and v is not None:
                velocity_mag = np.sqrt(u**2 + v**2)
                power = 0.5 * SEAWATER_DENSITY * velocity_mag**3

                if n_nodes is None:
                    n_nodes = len(u)
                    power_sum = np.zeros(n_nodes)

                ml = min(len(power), n_nodes)
                power_sum[:ml] += power[:ml]
                count += 1

    if count == 0:
        raise RuntimeError("No velocity data found after start_day cutoff")

    power_mean = power_sum / count
    return power_mean


def rasterize_to_geotiff(
    node_coords, power_values, output_path, resolution_m=500
):
    """Rasterize unstructured node data onto a regular grid and export as COG."""
    lon, lat = node_coords[:, 0], node_coords[:, 1]

    lon_min, lon_max = lon.min(), lon.max()
    lat_min, lat_max = lat.min(), lat.max()

    dx_deg = resolution_m / 111320.0
    dy_deg = resolution_m / 111320.0

    n_lon = int(np.ceil((lon_max - lon_min) / dx_deg)) + 1
    n_lat = int(np.ceil((lat_max - lat_min) / dy_deg)) + 1

    grid_lon = np.linspace(lon_min, lon_max, n_lon)
    grid_lat = np.linspace(lat_min, lat_max, n_lat)
    grid_lon_mesh, grid_lat_mesh = np.meshgrid(grid_lon, grid_lat)

    print(f"Rasterizing: {n_lon} × {n_lat} pixels ({resolution_m} m resolution)")

    power_grid = griddata(
        (lon, lat),
        power_values,
        (grid_lon_mesh, grid_lat_mesh),
        method="linear",
    )
    power_grid = np.nan_to_num(power_grid, nan=0.0)

    power_grid = power_grid[::-1, :]

    geotransform = (
        lon_min,
        dx_deg,
        0.0,
        lat_max,
        0.0,
        -dy_deg,
    )

    try:
        from osgeo import gdal, osr
    except ImportError:
        print("WARNING: GDAL Python bindings not found. Writing raw .npy file.")
        np.save(Path(output_path).with_suffix(".npy"), power_grid)
        print(f"Raw output saved to {Path(output_path).with_suffix('.npy')}")
        return

    driver = gdal.GetDriverByName("GTiff")
    dst = driver.Create(output_path, n_lon, n_lat, 1, gdal.GDT_Float32)

    dst.SetGeoTransform(geotransform)

    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    dst.SetProjection(srs.ExportToWkt())

    band = dst.GetRasterBand(1)
    band.WriteArray(power_grid)
    band.SetNoDataValue(0.0)
    band.SetDescription("Time-averaged tidal power density (W/m^2)")

    dst.BuildOverviews("NEAREST", [2, 4, 8, 16, 32])

    dst.SetMetadataItem("TIFFTAG_SOFTWARE", "tidal-oss postprocess.py")
    dst.SetMetadataItem("TIFFTAG_DATETIME", str(np.datetime64("now")))

    dst.FlushCache()
    dst = None

    print(f"GeoTIFF written to {output_path}")
    print(f"  Power density range: {power_grid[power_grid > 0].min():.2f} – "
          f"{power_grid.max():.2f} W/m²")
    print(f"  Mean: {power_grid[power_grid > 0].mean():.2f} W/m²")


def get_node_coords(input_dir: str, mesh_path: str = None):
    """Get mesh node coordinates from mesh file or HDF5 metadata."""
    if mesh_path and Path(mesh_path).exists():
        import meshio
        mesh = meshio.read(mesh_path)
        return mesh.points[:, :2]

    files = list(Path(input_dir).rglob("*.h5"))
    if not files:
        files = list(Path(input_dir).glob("*"))

    for fpath in files:
        if fpath.suffix == ".h5":
            try:
                with h5py.File(fpath, "r") as hf:
                    for key in hf.keys():
                        if key in ("coordinates", "nodes", "mesh"):
                            return np.array(hf[key])
            except Exception:
                continue

    n_nodes = 1000
    for fpath in files:
        if fpath.suffix == ".h5":
            try:
                with h5py.File(fpath, "r") as hf:
                    for key in hf.keys():
                        if key != "time":
                            ds = hf[key]
                            for k in ds.keys():
                                arr = np.array(ds[k]).ravel()
                                n_nodes = len(arr)
                                break
                    break
            except Exception:
                continue

    print(f"WARNING: Node coordinates not found — using synthetic regular grid ({n_nodes} nodes)")
    n = int(np.sqrt(n_nodes))
    lon = np.linspace(116, 130, n)
    lat = np.linspace(4, 22, n)
    lon_mesh, lat_mesh = np.meshgrid(lon, lat)
    return np.column_stack([lon_mesh.ravel()[:n_nodes], lat_mesh.ravel()[:n_nodes]])


def main():
    args = parse_args()

    input_dir = Path(args.input)
    if not input_dir.exists():
        print(f"ERROR: Input directory not found: {args.input}")
        sys.exit(1)

    print(f"Processing Thetis output from {input_dir}...")

    node_coords = get_node_coords(str(input_dir), args.mesh)
    print(f"  Nodes: {len(node_coords)}")

    power_mean = read_thetis_hdf5(str(input_dir), args.start_day)
    power_mean = np.clip(power_mean, 0, None)

    print(f"  Power density statistics:")
    print(f"    Max:    {power_mean.max():.2f} W/m²")
    print(f"    Mean:   {power_mean.mean():.2f} W/m²")
    print(f"    Median: {np.median(power_mean):.2f} W/m²")

    rasterize_to_geotiff(
        node_coords,
        power_mean,
        args.output,
        resolution_m=args.resolution,
    )


if __name__ == "__main__":
    main()
