#!/usr/bin/env python3
"""
Generate an unstructured triangular mesh for the Philippine maritime domain
using the Gmsh Python API.

Inputs:
  - Philippines landmass shapefile (GADM or OSM)
  - Domain bounding box and mesh resolution parameters

Output:
  - Gmsh .msh file with tagged physical groups:
      tag 1 = open ocean boundaries
      tag 2 = land boundaries
      tag 3 = domain interior
"""

import argparse
import sys
from pathlib import Path

try:
    import gmsh
except ImportError:
    print("ERROR: gmsh Python API not found. Install with: pip install gmsh")
    print("Or ensure the Gmsh SDK is on your PYTHONPATH.")
    sys.exit(1)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate unstructured triangular mesh from shapefile using Gmsh"
    )
    parser.add_argument(
        "--shapefile", type=str, required=True,
        help="Path to landmass shapefile (e.g., gadm41_PHL_0.shp)"
    )
    parser.add_argument(
        "--output", type=str, default="mesh_philippines.msh",
        help="Output mesh file path (default: mesh_philippines.msh)"
    )
    parser.add_argument(
        "--domain", type=float, nargs=4,
        default=[116.0, 130.0, 4.0, 22.0],
        metavar=("LON_MIN", "LON_MAX", "LAT_MIN", "LAT_MAX"),
        help="Domain bounding box (default: 116 130 4 22)"
    )
    parser.add_argument(
        "--lc-ocean", type=float, default=0.1,
        help="Characteristic length at open ocean (degrees, default: 0.1 ~10 km)"
    )
    parser.add_argument(
        "--lc-coast", type=float, default=0.005,
        help="Characteristic length near coasts (degrees, default: 0.005 ~500 m)"
    )
    parser.add_argument(
        "--simplify-tolerance", type=float, default=0.005,
        help="Simplify land boundary tolerance in degrees (default: 0.005)"
    )
    return parser.parse_args()


def load_land_polygon(shapefile_path: str, simplify_tolerance: float = 0.005):
    """
    Load the first polygon from the shapefile and simplify it.
    Returns simplified exterior coordinates as list of (lon, lat) tuples.
    """
    try:
        import geopandas as gpd
    except ImportError:
        print("ERROR: geopandas not found. Install with: pip install geopandas")
        sys.exit(1)

    gdf = gpd.read_file(shapefile_path)
    if len(gdf) == 0:
        raise ValueError(f"No features found in {shapefile_path}")

    # Use the largest polygon (mainland)
    gdf = gdf.to_crs("EPSG:4326")
    geom = gdf.geometry.iloc[0]
    if geom.geom_type == "MultiPolygon":
        # Take largest polygon
        geom = max(geom.geoms, key=lambda g: g.area)

    if simplify_tolerance > 0:
        geom = geom.simplify(simplify_tolerance, preserve_topology=True)

    coords = list(geom.exterior.coords)
    return coords


def build_mesh(
    output_path: str,
    land_coords: list,
    domain: tuple,
    lc_ocean: float,
    lc_coast: float,
):
    """Build the Gmsh mesh with ocean domain and land holes."""
    lon_min, lon_max, lat_min, lat_max = domain

    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 1)
    gmsh.model.add("philippines")

    # ---- Domain corners ----
    corners = [
        (lon_min, lat_min),
        (lon_max, lat_min),
        (lon_max, lat_max),
        (lon_min, lat_max),
    ]
    corner_tags = []
    for i, (x, y) in enumerate(corners):
        corner_tags.append(gmsh.model.geo.addPoint(x, y, 0, lc_ocean))

    # ---- Domain boundary lines ----
    boundary_lines = []
    for i in range(4):
        boundary_lines.append(
            gmsh.model.geo.addLine(corner_tags[i], corner_tags[(i + 1) % 4])
        )

    # ---- Land boundary points & lines ----
    land_point_tags = []
    for x, y in land_coords:
        land_point_tags.append(gmsh.model.geo.addPoint(x, y, 0, lc_coast))

    land_line_tags = []
    n_land = len(land_point_tags)
    for i in range(n_land):
        land_line_tags.append(
            gmsh.model.geo.addLine(land_point_tags[i], land_point_tags[(i + 1) % n_land])
        )

    # ---- Define surface with land hole ----
    domain_loop = gmsh.model.geo.addCurveLoop(boundary_lines)
    land_loop = gmsh.model.geo.addCurveLoop(land_line_tags)

    gmsh.model.geo.addPlaneSurface([domain_loop, land_loop])

    # ---- Physical groups ----
    # Tag 1: open ocean boundaries
    gmsh.model.addPhysicalGroup(1, boundary_lines, tag=1)
    gmsh.model.setPhysicalName(1, 1, "open_ocean")

    # Tag 2: land boundaries
    gmsh.model.addPhysicalGroup(1, land_line_tags, tag=2)
    gmsh.model.setPhysicalName(1, 2, "land")

    # Tag 3: domain interior
    surfaces = gmsh.model.getEntities(dim=2)
    if surfaces:
        surface_tags = [s[1] for s in surfaces]
        gmsh.model.addPhysicalGroup(2, surface_tags, tag=3)
        gmsh.model.setPhysicalName(2, 3, "domain")

    gmsh.model.geo.synchronize()

    # ---- Mesh generation ----
    gmsh.option.setNumber("Mesh.Algorithm", 6)       # Frontal-Delaunay
    gmsh.option.setNumber("Mesh.RecombinationAlgorithm", 0)
    gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 1)
    gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 1)

    gmsh.model.mesh.generate(2)

    # ---- Save ----
    gmsh.write(output_path)
    print(f"Mesh written to {output_path}")
    print(f"  Nodes: {len(gmsh.model.mesh.get_nodes()[0])}")
    print(f"  Elements: {len(gmsh.model.mesh.get_elements()[0])}")
    gmsh.finalize()


def main():
    args = parse_args()

    shapefile = Path(args.shapefile)
    if not shapefile.exists():
        print(f"ERROR: Shapefile not found: {args.shapefile}")
        print("Download from https://gadm.org/download_country_v3.html")

        # Generate a fallback simple mesh without land
        print("\nGenerating a simple rectangular mesh without a land boundary...")
        domain = tuple(args.domain)
        # Simple star-shaped land polygon as placeholder
        cx = (domain[0] + domain[1]) / 2
        cy = (domain[2] + domain[3]) / 2
        land_coords = [
            (cx + 2, cy),
            (cx + 2.5, cy + 2.5),
            (cx + 1, cy + 3),
            (cx - 1, cy + 3),
            (cx - 2.5, cy + 2.5),
            (cx - 2, cy),
            (cx - 2.5, cy - 2.5),
            (cx - 1, cy - 3),
            (cx + 1, cy - 3),
            (cx + 2.5, cy - 2.5),
        ]
    else:
        print(f"Loading land boundary from {args.shapefile}...")
        land_coords = load_land_polygon(args.shapefile, args.simplify_tolerance)

    domain = tuple(args.domain)
    print(f"Domain: lon=[{domain[0]}, {domain[1]}], lat=[{domain[2]}, {domain[3]}]")
    print(f"Ocean resolution: ~{args.lc_ocean * 111:.0f} km")
    print(f"Coast resolution: ~{args.lc_coast * 111 * 1000:.0f} m")
    print(f"Land boundary points: {len(land_coords)}")

    build_mesh(
        output_path=args.output,
        land_coords=land_coords,
        domain=domain,
        lc_ocean=args.lc_ocean,
        lc_coast=args.lc_coast,
    )


if __name__ == "__main__":
    main()
