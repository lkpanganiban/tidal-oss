"""Mesh generation and coordinate handling for the TELEMAC refinement workflow.

The screening model works in geographic longitude/latitude, while TELEMAC
integrates the shallow-water equations in a planar metric frame.  We therefore
project the refinement sub-domain into local tangent-plane metres (equirectangular
approximation) so that mesh spacing, bottom friction, Coriolis and current
speeds are physically consistent.  The projection origin is stored with every
case so the post-processor can map node coordinates (and velocities) back to
longitude/latitude for the web raster layers.

Two mesh sources are supported:

* ``generated`` -- a triangular mesh built by clipping the screening structured
  grid to a hotspot bounding box and triangulating each clipped cell.
* ``supplied`` -- an externally authored ``.slf`` mesh (e.g. Blue Kenue / Rubar /
  STBTEL).  Supplied meshes are assumed to already be in planar coordinates; the
  case manifest records whether those coordinates are local metres or raw
  longitude/latitude.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np

from .selafin import SerafinGeometry, read_geometry, write_geometry

METERS_PER_DEG_LAT = 110540.0


@dataclass
class RefinementMesh:
    """A TELEMAC mesh plus the projection needed to recover lon/lat."""

    path: str
    geometry: SerafinGeometry
    lon0: float
    lat0: float
    node_lon: np.ndarray
    node_lat: np.ndarray
    coordinates_are_meters: bool
    bbox: dict
    # Populated when the mesh is built from a screening grid with a land mask:
    # the IPOBO indices (1-based) of boundary points that are open (liquid).
    # ``None`` means "no land-aware classification was performed" and the
    # boundary classifier falls back to edge-based classification.
    liquid_ipobo: list[int] | None = None


def project_to_local_meters(
    lon: np.ndarray, lat: np.ndarray, lon0: float, lat0: float
) -> tuple[np.ndarray, np.ndarray]:
    """Equirectangular projection of lon/lat onto local tangent-plane metres."""
    lon = np.asarray(lon, dtype=np.float64)
    lat = np.asarray(lat, dtype=np.float64)
    x = (lon - lon0) * np.cos(np.radians(lat0)) * 111320.0
    y = (lat - lat0) * METERS_PER_DEG_LAT
    return x, y


def unproject_from_local_meters(
    x: np.ndarray, y: np.ndarray, lon0: float, lat0: float
) -> tuple[np.ndarray, np.ndarray]:
    """Inverse of :func:`project_to_local_meters`."""
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    lon = x / (np.cos(np.radians(lat0)) * 111320.0) + lon0
    lat = y / METERS_PER_DEG_LAT + lat0
    return lon, lat


def _clip_indices(grid, bbox: dict) -> tuple[int, int, int, int]:
    lon = grid.lon
    lat = grid.lat
    j_mask = (lat >= bbox["lat_min"]) & (lat <= bbox["lat_max"])
    i_mask = (lon >= bbox["lon_min"]) & (lon <= bbox["lon_max"])
    j_idx = np.where(j_mask.any(axis=1))[0]
    i_idx = np.where(i_mask.any(axis=0))[0]
    if j_idx.size == 0 or i_idx.size == 0:
        raise ValueError("bounding box contains no screening grid cells")
    return int(j_idx.min()), int(j_idx.max()), int(i_idx.min()), int(i_idx.max())


def _wet_mask(grid, j0: int, j1: int, i0: int, i1: int) -> np.ndarray:
    """Boolean wet mask for the clipped grid (True = water, False = land)."""
    if getattr(grid, "mask", None) is not None:
        return np.asarray(grid.mask[j0 : j1 + 1, i0 : i1 + 1], dtype=bool)
    md = float(getattr(grid, "min_depth", 2.0))
    return grid.h[j0 : j1 + 1, i0 : i1 + 1] >= md


def _is_dry_neighbor(grid, j0: int, i0: int, j: int, i: int, dj: int, di: int) -> bool:
    """True if the neighbour (4-connected) of (j, i) in full-grid coords is land.

    Neighbours that lie outside the full model grid are treated as open domain
    (not land), so boundary points on the open-water edges of the refinement box
    are not forced solid by an out-of-bounds lookup.
    """
    jj, ii = j0 + j + dj, i0 + i + di
    gmask = getattr(grid, "mask", None)
    if gmask is not None:
        if 0 <= jj < gmask.shape[0] and 0 <= ii < gmask.shape[1]:
            return not bool(gmask[jj, ii])
        return False
    h = grid.h
    md = float(getattr(grid, "min_depth", 2.0))
    if 0 <= jj < h.shape[0] and 0 <= ii < h.shape[1]:
        return float(h[jj, ii]) < md
    return False


def _subgrid_land_mask(
    lon_sub: np.ndarray, lat_sub: np.ndarray, land_shapefile: str
) -> np.ndarray:
    """Rasterise the land shapefile onto the (clipped) sub-grid.

    Uses ``all_touched=True`` so a coastline that falls between coarse (2 km)
    screening-grid centres still marks the adjacent water cells as land.  This
    gives the refinement mesh a proper coastline (so it follows the strait)
    instead of an open rectangular edge.
    """
    import fiona
    from affine import Affine
    from rasterio.features import rasterize

    ny, nx = lon_sub.shape
    dlon = float(lon_sub[0, 1] - lon_sub[0, 0])
    dlat = float(lat_sub[1, 0] - lat_sub[0, 0])
    lon_ul = float(lon_sub[0, 0]) - dlon / 2.0
    lat_ul = float(lat_sub[0, 0]) - dlat / 2.0
    transform = Affine(dlon, 0.0, lon_ul, 0.0, dlat, lat_ul)
    with fiona.open(land_shapefile) as src:
        geoms = [(feat["geometry"], 1) for feat in src]
    arr = rasterize(
        geoms,
        out_shape=(ny, nx),
        transform=transform,
        fill=0,
        dtype="uint8",
        all_touched=True,
    )
    return arr.astype(bool)


def generate_mesh_from_grid(
    grid,
    bbox: dict,
    out_path: str,
    *,
    title: str = "TIDAL-OSS GENERATED REFINEMENT",
    edge_types: dict[str, str] | None = None,
    land_shapefile: str | None = None,
) -> RefinementMesh:
    """Triangulate the screening grid clipped to ``bbox`` into a TELEMAC mesh.

    Land cells are excluded from the mesh so the coastline forms natural solid
    walls (``LIEBOR=2``).  Boundary points are then classified:

    * a boundary node that touches a land cell is a **coastline** point → solid;
    * a boundary node on an open-water edge of the box is liquid/solid according
      to ``edge_types`` (defaulting to the supplied mapping, otherwise solid).

    When ``edge_types`` is given, the IPOBO indices of the open (liquid) boundary
    points are stored on the returned mesh (``mesh.liquid_ipobo``) so the boundary
    writer can use them directly.  Without ``edge_types`` the mesh is returned
    with ``liquid_ipobo=None`` and the caller falls back to edge-based
    classification.
    """
    j0, j1, i0, i1 = _clip_indices(grid, bbox)
    ny_loc = j1 - j0 + 1
    nx_loc = i1 - i0 + 1

    lon_sub = grid.lon[j0 : j1 + 1, i0 : i1 + 1]
    lat_sub = grid.lat[j0 : j1 + 1, i0 : i1 + 1]
    h_sub = grid.h[j0 : j1 + 1, i0 : i1 + 1]
    wet = _wet_mask(grid, j0, j1, i0, i1) & np.isfinite(h_sub)

    # Refine the land mask at the mesh resolution so thin coastlines that the
    # coarse (2 km) screening grid misses are still excluded from the mesh.
    if land_shapefile:
        try:
            sub_land = _subgrid_land_mask(lon_sub, lat_sub, land_shapefile)
            wet = wet & (~sub_land)
        except Exception:
            pass

    # Assign a mesh node only to wet grid cells.
    node_id = -np.ones((ny_loc, nx_loc), dtype=np.int64)
    node_ji: list[tuple[int, int]] = []
    node_lon: list[float] = []
    node_lat: list[float] = []
    node_h: list[float] = []
    for j in range(ny_loc):
        for i in range(nx_loc):
            if wet[j, i]:
                node_id[j, i] = len(node_ji)
                node_ji.append((j, i))
                node_lon.append(float(lon_sub[j, i]))
                node_lat.append(float(lat_sub[j, i]))
                node_h.append(float(h_sub[j, i]))

    if len(node_ji) == 0:
        raise ValueError("no wet cells in the refinement bounding box")

    node_lon = np.asarray(node_lon, dtype=np.float64)
    node_lat = np.asarray(node_lat, dtype=np.float64)
    node_h = np.asarray(node_h, dtype=np.float64)

    # Triangulate only quads whose four corners are all wet.
    ikle = []
    for j in range(ny_loc - 1):
        for i in range(nx_loc - 1):
            a = node_id[j, i]
            b = node_id[j, i + 1]
            c = node_id[j + 1, i]
            d = node_id[j + 1, i + 1]
            if a >= 0 and b >= 0 and c >= 0 and d >= 0:
                ikle.append([a, b, d])
                ikle.append([a, d, c])
    ikle = np.asarray(ikle, dtype=np.int64)

    lon0 = float(node_lon.mean())
    lat0 = float(node_lat.mean())
    x_m, y_m = project_to_local_meters(node_lon, node_lat, lon0, lat0)

    bed_elevation = -node_h.astype(np.float32)
    geom = write_geometry(
        out_path,
        x_m.astype(np.float32),
        y_m.astype(np.float32),
        ikle,
        title=title,
        bed_elevation=bed_elevation,
        var_name="ELEVATION Z",
        var_unit="M",
    )

    liquid_ipobo = None
    if edge_types is not None:
        ipobo = geom.ipobo
        nbnd = int((ipobo > 0).sum())
        liquid_ipobo = []
        for k in range(1, nbnd + 1):
            node = int(np.where(ipobo == k)[0][0])
            j, i = node_ji[node]
            # Coastline: any land neighbour forces a solid (no-flux) wall.
            touches_land = any(
                _is_dry_neighbor(grid, j0, i0, j, i, dj, di)
                for dj, di in ((-1, 0), (1, 0), (0, -1), (0, 1))
            )
            if touches_land:
                continue
            on_left = i == 0
            on_right = i == nx_loc - 1
            on_bottom = j == 0
            on_top = j == ny_loc - 1
            if not (on_left or on_right or on_bottom or on_top):
                # Interior boundary (e.g. a hole) -> solid wall.
                continue
            if on_left:
                edge = "left"
            elif on_right:
                edge = "right"
            elif on_top:
                edge = "top"
            else:
                edge = "bottom"
            if edge_types.get(edge, "solid") == "liquid":
                liquid_ipobo.append(k)

    return RefinementMesh(
        path=out_path,
        geometry=geom,
        lon0=lon0,
        lat0=lat0,
        node_lon=node_lon,
        node_lat=node_lat,
        coordinates_are_meters=True,
        bbox=bbox,
        liquid_ipobo=liquid_ipobo,
    )


def load_supplied_mesh(
    path: str,
    bbox: dict | None = None,
    *,
    coordinates_are_meters: bool = True,
    lon0: float = 0.0,
    lat0: float = 0.0,
) -> RefinementMesh:
    """Load an externally authored ``.slf`` mesh.

    When the supplied mesh is already in longitude/latitude (``coordinates_are_meters``
    is ``False``) the node lon/lat are taken directly from the file.  Otherwise the
    caller must provide the projection origin used when the mesh was built so node
    coordinates can be unprojected to geographic space for the raster layers.
    """
    geom = read_geometry(path)
    if coordinates_are_meters:
        node_lon, node_lat = unproject_from_local_meters(geom.x, geom.y, lon0, lat0)
    else:
        node_lon, node_lat = geom.x.astype(np.float64), geom.y.astype(np.float64)
        if bbox is None:
            bbox = {
                "lon_min": float(node_lon.min()),
                "lon_max": float(node_lon.max()),
                "lat_min": float(node_lat.min()),
                "lat_max": float(node_lat.max()),
            }
    if bbox is None:
        bbox = {
            "lon_min": float(node_lon.min()),
            "lon_max": float(node_lon.max()),
            "lat_min": float(node_lat.min()),
            "lat_max": float(node_lat.max()),
        }
    return RefinementMesh(
        path=path,
        geometry=geom,
        lon0=lon0,
        lat0=lat0,
        node_lon=node_lon,
        node_lat=node_lat,
        coordinates_are_meters=coordinates_are_meters,
        bbox=bbox,
    )


def _points_in_mesh(
    flat_lon: np.ndarray,
    flat_lat: np.ndarray,
    node_lon: np.ndarray,
    node_lat: np.ndarray,
    triangles: np.ndarray,
) -> np.ndarray:
    """Boolean mask: which target points fall inside the unstructured mesh.

    ``triangles`` is the ``(Ne, 3)`` 0-based element connectivity.  A target
    point is "inside" if it lies in any triangle (barycentric test).  This lets
    us restrict rasterised fields to the actual (possibly non-convex) mesh
    footprint instead of filling the whole rectangular bounding box.
    """
    pts = np.column_stack([flat_lon, flat_lat])  # (n, 2)
    v0 = np.column_stack([node_lon[triangles[:, 0]], node_lat[triangles[:, 0]]])
    v1 = np.column_stack([node_lon[triangles[:, 1]], node_lat[triangles[:, 1]]])
    v2 = np.column_stack([node_lon[triangles[:, 2]], node_lat[triangles[:, 2]]])
    e1 = v1 - v0
    e2 = v2 - v0
    d = pts[:, None, :] - v0[None, :, :]  # (n, Ne, 2)
    det = e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]  # (Ne,)
    a = (d[..., 0] * e2[:, 1][None, :] - d[..., 1] * e2[:, 0][None, :]) / det[None, :]
    b = (d[..., 1] * e1[:, 0][None, :] - d[..., 0] * e1[:, 1][None, :]) / det[None, :]
    eps = 1e-9
    inside_tri = (a >= -eps) & (b >= -eps) & ((a + b) <= 1.0 + eps)
    return inside_tri.any(axis=1)


def rasterize_to_grid(
    values: np.ndarray,
    node_lon: np.ndarray,
    node_lat: np.ndarray,
    target_lon: np.ndarray,
    target_lat: np.ndarray,
    triangles: np.ndarray | None = None,
) -> np.ndarray:
    """Interpolate unstructured node values onto a regular lon/lat grid.

    Uses scipy ``griddata`` (linear, falling back to nearest) when available;
    otherwise a simple inverse-distance weighting is used so the post-processor
    does not hard-depend on scipy being importable at call time.

    When ``triangles`` (the ``(Ne, 3)`` element connectivity) is supplied, the
    result is masked to the actual mesh footprint: target points that fall
    outside every triangle are set to NaN so land / outside-mesh cells do not
    get spurious interpolated values (which would otherwise render as a solid
    rectangle covering the whole bounding box).
    """
    values = np.asarray(values, dtype=np.float64)
    node_lon = np.asarray(node_lon, dtype=np.float64).ravel()
    node_lat = np.asarray(node_lat, dtype=np.float64).ravel()
    ny, nx = target_lat.shape
    flat_lon = target_lon.ravel()
    flat_lat = target_lat.ravel()
    valid = np.isfinite(values)

    try:
        from scipy.interpolate import griddata

        pts = np.column_stack([node_lon[valid], node_lat[valid]])
        src = values[valid]
        out = griddata(pts, src, (flat_lon, flat_lat), method="linear")
        if np.isnan(out).any():
            out_near = griddata(pts, src, (flat_lon, flat_lat), method="nearest")
            out = np.where(np.isnan(out), out_near, out)
    except Exception:
        out = _idw(node_lon[valid], node_lat[valid], values[valid], flat_lon, flat_lat)

    if triangles is not None:
        inside = _points_in_mesh(flat_lon, flat_lat, node_lon, node_lat, triangles)
        out = np.where(inside, out, np.nan)

    return out.reshape(ny, nx)


def _idw(
    src_lon: np.ndarray,
    src_lat: np.ndarray,
    src_val: np.ndarray,
    tgt_lon: np.ndarray,
    tgt_lat: np.ndarray,
    power: float = 2.0,
) -> np.ndarray:
    out = np.full(tgt_lon.shape, np.nan)
    for k in range(tgt_lon.shape[0]):
        dlon = src_lon - tgt_lon[k]
        dlat = src_lat - tgt_lat[k]
        d2 = dlon**2 + dlat**2
        if d2.min() == 0.0:
            out[k] = src_val[d2.argmin()]
            continue
        w = 1.0 / np.power(d2, power / 2.0)
        out[k] = float(np.sum(w * src_val) / np.sum(w))
    return out


def mesh_manifest(mesh: RefinementMesh) -> dict:
    """Serialize the projection/case metadata needed for post-processing."""
    if mesh.geometry is not None and mesh.geometry.values is not None:
        node_depth = (-np.asarray(mesh.geometry.values, dtype=np.float64)).tolist()
    else:
        node_depth = None
    return {
        "path": mesh.path,
        "lon0": mesh.lon0,
        "lat0": mesh.lat0,
        "coordinates_are_meters": mesh.coordinates_are_meters,
        "node_lon": mesh.node_lon.tolist(),
        "node_lat": mesh.node_lat.tolist(),
        "node_depth": node_depth,
        "bbox": mesh.bbox,
    }


def save_manifest(mesh: RefinementMesh, path: str) -> None:
    with open(path, "w") as f:
        json.dump(mesh_manifest(mesh), f, indent=2)
