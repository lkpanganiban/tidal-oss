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

    from ..bathymetry import _rasterise_land_geoms

    ny, nx = lon_sub.shape
    dlon = float(lon_sub[0, 1] - lon_sub[0, 0])
    dlat = float(lat_sub[1, 0] - lat_sub[0, 0])
    lon_ul = float(lon_sub[0, 0]) - dlon / 2.0
    lat_ul = float(lat_sub[0, 0]) - dlat / 2.0
    transform = Affine(dlon, 0.0, lon_ul, 0.0, dlat, lat_ul)
    with fiona.open(land_shapefile) as src:
        geoms = [(feat["geometry"], 1) for feat in src]
    return _rasterise_land_geoms(geoms, (ny, nx), transform, all_touched=True).astype(
        bool
    )


def _assign_node_ids(wet: np.ndarray) -> tuple[np.ndarray, list[tuple[int, int]]]:
    """Assign sequential mesh-node ids to wet cells of a boolean mask.

    Returns ``(node_id, node_ji)`` where ``node_id`` is a 2-D int64 array
    (``-1`` for dry cells) and ``node_ji`` is the list of ``(j, i)`` indices
    (in mask-local coordinates) of the assigned nodes, in id order.
    """
    ny_loc, nx_loc = wet.shape
    node_id = -np.ones((ny_loc, nx_loc), dtype=np.int64)
    node_ji: list[tuple[int, int]] = []
    for j in range(ny_loc):
        for i in range(nx_loc):
            if wet[j, i]:
                node_id[j, i] = len(node_ji)
                node_ji.append((j, i))
    return node_id, node_ji


def _gather_node_coords(node_ji, lon2d, lat2d, depth2d):
    """Collect node lon/lat/depth arrays from a node-index list."""
    node_lon = np.array([float(lon2d[j, i]) for (j, i) in node_ji], dtype=np.float64)
    node_lat = np.array([float(lat2d[j, i]) for (j, i) in node_ji], dtype=np.float64)
    node_h = np.array([float(depth2d[j, i]) for (j, i) in node_ji], dtype=np.float64)
    return node_lon, node_lat, node_h


def _triangulate_quads(node_id: np.ndarray) -> np.ndarray:
    """Triangulate every quad whose four corners are wet -> ``(n, 3)`` ikle.

    Adjacent wet cells sharing all four corners yield two triangles each.
    """
    ny_loc, nx_loc = node_id.shape
    ikle = []
    for j in range(ny_loc - 1):
        for i in range(nx_loc - 1):
            a, b = node_id[j, i], node_id[j, i + 1]
            c, d = node_id[j + 1, i], node_id[j + 1, i + 1]
            if a >= 0 and b >= 0 and c >= 0 and d >= 0:
                ikle.append([a, b, d])
                ikle.append([a, d, c])
    return np.asarray(ikle, dtype=np.int64)


def _classify_liquid_boundaries(
    geom,
    node_ji: list[tuple[int, int]],
    nx: int,
    ny: int,
    is_dry,
    edge_types: dict[str, str],
) -> list[int]:
    """Return the IPOBO indices of liquid boundary points.

    A boundary node is solid when any 4-connected neighbour is land (so
    coastlines form no-flux walls).  Otherwise its edge -- ``left``/``right``/
    ``top``/``bottom`` from its position on the mesh rectangle -- is looked up
    in ``edge_types`` (default ``solid``).  Interior (hole) boundary nodes are
    always solid.

    ``is_dry(j, i) -> bool`` reports whether the grid cell at (j, i) is land,
    letting each builder supply its own land definition (screening-grid
    neighbour vs fine-grid wet mask).
    """
    ipobo = geom.ipobo
    nbnd = int((ipobo > 0).sum())
    liquid_ipobo: list[int] = []
    for k in range(1, nbnd + 1):
        node = int(np.where(ipobo == k)[0][0])
        j, i = node_ji[node]
        if any(is_dry(j + dj, i + di) for dj, di in ((-1, 0), (1, 0), (0, -1), (0, 1))):
            continue
        if i == 0:
            edge = "left"
        elif i == nx - 1:
            edge = "right"
        elif j == 0:
            edge = "bottom"
        elif j == ny - 1:
            edge = "top"
        else:
            continue  # interior hole boundary -> solid
        if edge_types.get(edge, "solid") == "liquid":
            liquid_ipobo.append(k)
    return liquid_ipobo


def _finalize_refinement_mesh(
    out_path: str,
    node_lon: np.ndarray,
    node_lat: np.ndarray,
    node_h: np.ndarray,
    ikle: np.ndarray,
    *,
    title: str,
    bbox: dict,
) -> RefinementMesh:
    """Project nodes, write the SERAFIN geometry, and build the RefinementMesh."""
    lon0 = float(node_lon.mean())
    lat0 = float(node_lat.mean())
    x_m, y_m = project_to_local_meters(node_lon, node_lat, lon0, lat0)
    geom = write_geometry(
        out_path,
        x_m.astype(np.float32),
        y_m.astype(np.float32),
        ikle,
        title=title,
        bed_elevation=-node_h.astype(np.float32),
        var_name="ELEVATION Z",
        var_unit="M",
    )
    return RefinementMesh(
        path=out_path,
        geometry=geom,
        lon0=lon0,
        lat0=lat0,
        node_lon=node_lon,
        node_lat=node_lat,
        coordinates_are_meters=True,
        bbox=bbox,
    )


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

    node_id, node_ji = _assign_node_ids(wet)
    if not node_ji:
        raise ValueError("no wet cells in the refinement bounding box")

    node_lon, node_lat, node_h = _gather_node_coords(node_ji, lon_sub, lat_sub, h_sub)
    ikle = _triangulate_quads(node_id)
    mesh = _finalize_refinement_mesh(
        out_path, node_lon, node_lat, node_h, ikle, title=title, bbox=bbox
    )

    if edge_types is not None:
        # Any neighbour of a boundary node that is land (outside the wet mask)
        # forces a no-flux coastline wall.
        def is_dry(jj: int, ii: int) -> bool:
            return _is_dry_neighbor(grid, j0, i0, jj, ii, 0, 0)

        mesh.liquid_ipobo = _classify_liquid_boundaries(
            mesh.geometry, node_ji, nx_loc, ny_loc, is_dry, edge_types
        )
    return mesh


def generate_mesh_refined(
    bbox: dict,
    out_path: str,
    *,
    resolution_m: float,
    gebco_path: str,
    land_shapefile: str | None = None,
    edge_types: dict[str, str] | None = None,
    min_depth: float = 2.0,
    max_depth: float = 6000.0,
    title: str = "TIDAL-OSS REFINED MESH",
    max_nodes: int = 60000,
    min_island_cells: int = 12,
    parent_grid=None,
    depth_source: str = "parent",
) -> RefinementMesh:
    """Build a genuinely refined TELEMAC mesh.

    ``depth_source`` selects the bathymetry the refinement runs on:

    * ``"parent"`` (default) -- sample the screening grid's own depth and wet
      mask onto the fine nodes.  The child then shares the parent's channel
      depths, coastline and forcing, so refinement resolution is the *only*
      difference between the two models and the zoom view reconciles with the
      national view.
    * ``"gebco"`` -- sample native-resolution GEBCO with the high-resolution
      land polygon.  Physically finer, but the differing bathymetry makes the
      refined currents diverge from the parent (reported in reconciliation).

    Boundary nodes are liquid when they sit on an edge configured as
    ``"liquid"`` in ``edge_types`` *and* their inward neighbour is wet; nodes
    adjacent to any dry cell are coastline (solid).  The IPOBO indices of the
    liquid points are stored on the returned mesh (``liquid_ipobo``).

    Raises ``ValueError`` when the liquid boundaries do not share a single
    connected wet component (i.e. there is no through-flow path), or when the
    node budget ``max_nodes`` is exceeded.
    """
    import math as _math

    from model.bathymetry import build_land_mask, load_gebco

    lat_mid = 0.5 * (bbox["lat_min"] + bbox["lat_max"])
    dlon = resolution_m / (111320.0 * _math.cos(_math.radians(lat_mid)))
    dlat = resolution_m / 110540.0
    nx = max(3, int(round((bbox["lon_max"] - bbox["lon_min"]) / dlon)) + 1)
    ny = max(3, int(round((bbox["lat_max"] - bbox["lat_min"]) / dlat)) + 1)
    if nx * ny > max_nodes:
        raise ValueError(
            f"refined mesh needs {nx * ny} nodes at {resolution_m:g} m over the "
            f"{(bbox['lon_max'] - bbox['lon_min']) * 111.32:.0f} x "
            f"{(bbox['lat_max'] - bbox['lat_min']) * 110.54:.0f} km box "
            f"(budget {max_nodes}); increase telemac2d.mesh.resolution_m or "
            "shrink the region margin"
        )

    lon1d = np.linspace(bbox["lon_min"], bbox["lon_max"], nx)
    lat1d = np.linspace(bbox["lat_min"], bbox["lat_max"], ny)
    lon2d, lat2d = np.meshgrid(lon1d, lat1d)

    from scipy.interpolate import RegularGridInterpolator

    pts = np.column_stack([lat2d.ravel(), lon2d.ravel()])

    if depth_source == "parent" and parent_grid is not None:
        # Parent-nested bathymetry: the child inherits the screening grid's
        # exact depths and wet mask (horizontally refined), so bathymetry,
        # forcing and drag are identical to the parent and resolution is the
        # only remaining difference.
        plat1 = np.asarray(parent_grid.lat, dtype=np.float64)[:, 0]
        plon1 = np.asarray(parent_grid.lon, dtype=np.float64)[0, :]
        ph = np.asarray(parent_grid.h, dtype=np.float64)
        pmask = np.asarray(parent_grid.mask, dtype=bool)
        if plat1[0] > plat1[-1]:
            plat1 = plat1[::-1]
            ph = ph[::-1, :]
            pmask = pmask[::-1, :]
        interp_h = RegularGridInterpolator(
            (plat1, plon1),
            ph,
            # Nearest, not bilinear: bilinear smoothing rounds the parent's
            # shallow channel cells — the very cells that carry its jets —
            # and the refined currents then fall far below the parent's.
            method="nearest",
            bounds_error=False,
            fill_value=None,
        )
        h_at = interp_h(pts).reshape(ny, nx)
        # Nearest for the mask — a wet/land blend would create phantom coasts.
        interp_m = RegularGridInterpolator(
            (plat1, plon1),
            pmask.astype(np.float64),
            method="nearest",
            bounds_error=False,
            fill_value=None,
        )
        wet = interp_m(pts).reshape(ny, nx) > 0.5
        depth = np.clip(np.maximum(h_at, 0.0), min_depth, max_depth)
        wet &= depth >= min_depth
    else:
        # Native-resolution GEBCO sample at every node.
        g_lon, g_lat, g_elev = load_gebco(
            gebco_path,
            lon_min=bbox["lon_min"] - dlon,
            lon_max=bbox["lon_max"] + dlon,
            lat_min=bbox["lat_min"] - dlat,
            lat_max=bbox["lat_max"] + dlat,
        )
        interp = RegularGridInterpolator(
            (g_lat, g_lon), g_elev, bounds_error=False, fill_value=None
        )
        elev = interp(pts).reshape(ny, nx)

        wet = elev <= 0.0
        depth = np.clip(np.maximum(-elev, 0.0), min_depth, max_depth)
        wet &= depth >= min_depth

        if land_shapefile:
            try:
                land = build_land_mask(lon1d, lat1d, land_shapefile)
                wet &= ~land
            except Exception:
                pass

    # Flood checkerboard corners (2x2 blocks wet in one diagonal only) and
    # then any quad-graph pinch: a wet cell whose only mesh connections are
    # two *opposite* quads (along a diagonal staircase coastline) makes the
    # water rim pass through a single node twice — a "keyhole" that BIEF
    # cannot traverse (STOSEG "wrong number of segments").  Flooding the dry
    # diagonal cell restores the missing quad and removes the pinch.
    def _flood_checkerboards(w: np.ndarray) -> np.ndarray:
        d1 = w[:-1, :-1] & ~w[:-1, 1:] & ~w[1:, :-1] & w[1:, 1:]
        d2 = ~w[:-1, :-1] & w[:-1, 1:] & w[1:, :-1] & ~w[1:, 1:]
        flood = np.zeros_like(w)
        flood[:-1, :-1] |= d1
        flood[1:, 1:] |= d1
        flood[:-1, 1:] |= d2
        flood[1:, :-1] |= d2
        return w | flood

    wet = _flood_checkerboards(wet)

    def _pinch_flood(w: np.ndarray) -> np.ndarray:
        """Flood a dry cell completing a missing quad at every pinch node."""
        ny, nx = w.shape
        # q[j, i] = quad whose SE corner cell is (j, i), defined for 1<=j<=ny-1
        q = np.zeros((ny, nx), dtype=bool)
        q[1:, 1:] = w[:-1, :-1] & w[:-1, 1:] & w[1:, :-1] & w[1:, 1:]
        qSE = q[1 : ny - 1, 1 : nx - 1]
        qNW = q[2:ny, 2:nx]
        qSW = q[1 : ny - 1, 2:nx]
        qNE = q[2:ny, 1 : nx - 1]
        pinch_a = qSE & qNW & ~qSW & ~qNE  # missing SW / NE quads
        pinch_b = qSW & qNE & ~qSE & ~qNW  # missing SE / NW quads
        out = w.copy()
        for j, i in np.argwhere(pinch_a) + 1:
            # SW quad members: (j-1,i), (j-1,i+1), (j,i+1); NE: (j+1,i-1), (j+1,i), (j,i-1)
            for cand in ((j - 1, i + 1), (j - 1, i), (j, i + 1)):
                if not out[cand]:
                    out[cand] = True
                    break
            else:
                for cand in ((j + 1, i - 1), (j + 1, i), (j, i - 1)):
                    if not out[cand]:
                        out[cand] = True
                        break
        for j, i in np.argwhere(pinch_b) + 1:
            # SE quad members: (j-1,i-1), (j-1,i), (j,i-1); NW: (j+1,i+1), (j+1,i), (j,i+1)
            for cand in ((j - 1, i - 1), (j - 1, i), (j, i - 1)):
                if not out[cand]:
                    out[cand] = True
                    break
            else:
                for cand in ((j + 1, i + 1), (j + 1, i), (j, i + 1)):
                    if not out[cand]:
                        out[cand] = True
                        break
        return out

    for _ in range(30):
        fixed = _pinch_flood(wet)
        if fixed.sum() == wet.sum():
            break
        wet = _flood_checkerboards(fixed)

    # Drop tiny wet islets (below ``min_island_cells``): they would only add
    # unresolved rims to the mesh.
    try:
        from scipy import ndimage

        lab, nlab = ndimage.label(wet, structure=np.ones((3, 3)))
        sizes = np.bincount(lab.ravel())
        sizes[0] = 0
        wet &= sizes[lab] >= min_island_cells
    except ImportError:
        pass

    # --- nodes on wet cells ---
    node_id, node_ji = _assign_node_ids(wet)
    if not node_ji:
        raise ValueError("no wet cells in the refinement bounding box")

    node_lon, node_lat, node_h = _gather_node_coords(node_ji, lon2d, lat2d, depth)
    ikle = _triangulate_quads(node_id)

    # Prune nodes not referenced by any element (isolated wet cells — a wet
    # node whose four-neighbour quads are all broken).  An orphan node has no
    # element but is still counted as a boundary point by BIEF, which rejects
    # the mesh with "STOSEG: WRONG NUMBER OF SEGMENTS".
    used = np.unique(ikle)
    if used.size != node_lon.size:
        remap = -np.ones(node_lon.size, dtype=np.int64)
        remap[used] = np.arange(used.size)
        ikle = remap[ikle]
        node_lon = node_lon[used]
        node_lat = node_lat[used]
        node_h = node_h[used]
        node_ji = [node_ji[u] for u in used]

    mesh = _finalize_refinement_mesh(
        out_path, node_lon, node_lat, node_h, ikle, title=title, bbox=bbox
    )

    def _dry(j: int, i: int) -> bool:
        if 0 <= j < ny and 0 <= i < nx:
            return not bool(wet[j, i])
        return False  # outside the box counts as open water

    liquid_ipobo = None
    if edge_types is not None:
        liquid_ipobo = _classify_liquid_boundaries(
            mesh.geometry, node_ji, nx, ny, _dry, edge_types
        )

    _validate_throughflow(
        wet, edge_types, liquid_ipobo, node_ji, mesh.geometry.ipobo, nx, ny
    )

    mesh.liquid_ipobo = liquid_ipobo
    return mesh


def _validate_throughflow(
    wet: np.ndarray,
    edge_types: dict[str, str] | None,
    liquid_ipobo: list[int] | None,
    node_ji: list[tuple[int, int]],
    ipobo: np.ndarray,
    nx: int,
    ny: int,
) -> None:
    """Reject domains whose liquid boundaries have no wet path between them.

    Uses 4-connected component labelling of the wet mask: every liquid
    boundary node must belong to the same wet component, otherwise the tide
    cannot propagate through the domain and the TELEMAC run would refine a
    hydraulically dead box.

    When ``edge_types`` is ``None`` the boundary classification is deferred to
    the edge-based fallback (:func:`model.telemac.boundaries.classify_boundary_points`),
    so no through-flow validation is performed here.
    """
    if edge_types is None:
        return
    liquid_edges = [
        e for e in ("left", "right", "top", "bottom") if edge_types.get(e) == "liquid"
    ]
    if not liquid_edges or not liquid_ipobo:
        raise ValueError(
            "refinement domain has no usable liquid boundary "
            f"(edge_types={edge_types}); widen the region or adjust margin"
        )
    try:
        from scipy import ndimage
    except ImportError:
        return  # validation is best-effort without scipy

    labels, _ = ndimage.label(wet)
    comps = set()
    for k in liquid_ipobo:
        node = int(np.where(ipobo == k)[0][0])
        j, i = node_ji[node]
        lab = int(labels[j, i])
        if lab == 0:
            raise ValueError("liquid boundary node classified on a dry cell")
        comps.add(lab)
    if len(comps) > 1:
        raise ValueError(
            "liquid boundaries span "
            f"{len(comps)} disconnected wet components — no through-flow path; "
            "widen the region so both open edges reach the same channel"
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


class MeshRasterizer:
    """Fast repeated node→grid interpolation for one mesh/target pair.

    Building scipy's ``griddata`` per frame re-runs Delaunay triangulation
    and (with the triangle-footprint mask) an O(targets x triangles) point
    test — minutes per case at refinement-scale meshes.  Here the geometry
    work (Delaunay, per-target barycentric weights, footprint mask, nearest
    fallback tree) is done once; each :meth:`raster` call is then a small
    gather and matrix product.
    """

    _CHUNK = 512  # target points per footprint chunk (bounds memory)

    def __init__(
        self,
        node_lon: np.ndarray,
        node_lat: np.ndarray,
        target_lon: np.ndarray,
        target_lat: np.ndarray,
        triangles: np.ndarray | None = None,
    ) -> None:
        from scipy.spatial import Delaunay, cKDTree

        node_lon = np.asarray(node_lon, dtype=np.float64).ravel()
        node_lat = np.asarray(node_lat, dtype=np.float64).ravel()
        self.ny, self.nx = target_lat.shape
        tgt = np.column_stack(
            [
                np.asarray(target_lon, dtype=np.float64).ravel(),
                np.asarray(target_lat, dtype=np.float64).ravel(),
            ]
        )
        pts = np.column_stack([node_lon, node_lat])
        self._tree = cKDTree(pts)

        tri = Delaunay(pts)
        simplex = tri.find_simplex(tgt)
        inside_hull = simplex >= 0
        tid = np.where(inside_hull, simplex, 0)
        transf = tri.transform[tid]  # (n, 3, 2)
        d = tgt - transf[:, 2]
        b1 = np.einsum("ij,ij->i", d, transf[:, 0])
        b2 = np.einsum("ij,ij->i", d, transf[:, 1])
        self._w = np.column_stack([b1, b2, 1.0 - b1 - b2])
        self._vidx = tri.simplices[tid]
        self._inside_hull = inside_hull

        # Mesh-footprint mask: target points that fall inside at least one of
        # the mesh's own triangles (respects concave coastlines; Delaunay
        # alone would fill the convex hull across bays and land).
        self._inside_mesh = (
            self._footprint_mask(tgt, node_lon, node_lat, triangles)
            if triangles is not None
            else np.ones(tgt.shape[0], dtype=bool)
        )
        # Points inside the hull but outside the mesh: nearest-neighbour fill
        # (matches the legacy griddata+fallback behaviour before masking).
        self._nearest_idx = self._tree.query(tgt)[1]

    def _footprint_mask(self, tgt, node_lon, node_lat, triangles) -> np.ndarray:
        triangles = np.asarray(triangles, dtype=np.int64)
        v0x = node_lon[triangles[:, 0]]
        v0y = node_lat[triangles[:, 0]]
        e1x = node_lon[triangles[:, 1]] - v0x
        e1y = node_lat[triangles[:, 1]] - v0y
        e2x = node_lon[triangles[:, 2]] - v0x
        e2y = node_lat[triangles[:, 2]] - v0y
        det = e1x * e2y - e1y * e2x
        out = np.zeros(tgt.shape[0], dtype=bool)
        for s in range(0, tgt.shape[0], self._CHUNK):
            chunk = tgt[s : s + self._CHUNK]
            dx = chunk[None, :, 0] - v0x[:, None]
            dy = chunk[None, :, 1] - v0y[:, None]
            a = (dx * e2y[:, None] - dy * e2x[:, None]) / det[:, None]
            b = (dy * e1x[:, None] - dx * e1y[:, None]) / det[:, None]
            eps = 1e-9
            out[s : s + self._CHUNK] = (
                (a >= -eps) & (b >= -eps) & ((a + b) <= 1.0 + eps)
            ).any(axis=0)
        return out

    def raster(self, values: np.ndarray) -> np.ndarray:
        """Interpolate one frame of node values onto the target grid."""
        vals = np.asarray(values, dtype=np.float64).ravel()
        out = np.einsum("ij,ij->i", self._w, vals[self._vidx])
        outside = ~self._inside_hull
        if outside.any():
            out[outside] = vals[self._nearest_idx[outside]]
        out[~self._inside_mesh] = np.nan
        return out.reshape(self.ny, self.nx)


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
