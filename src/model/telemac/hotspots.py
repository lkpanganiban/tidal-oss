"""Cluster screening hotspots and assemble TELEMAC refinement cases.

Hotspots produced by the screening model are point features in geographic
space.  A refinement case needs a contiguous sub-domain, so we greedily cluster
the hotspot points (by great-circle proximity, highest-power-first) into a small
number of regions, expand each by a safety margin, and emit one TELEMAC case
directory per region.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field

import numpy as np

from ..utils import haversine_distance_m


@dataclass
class HotspotRegion:
    """A clustered, margin-expanded refinement region.

    ``axis`` is the dominant orientation of the hotspot cluster ("EW" or
    "NS") computed by PCA over the member points.  The refinement box is
    elongated *along* that axis and the liquid (tidal forcing) edges are the
    two box edges perpendicular to it, so the imposed tide propagates
    through-flow along the channel rather than sloshing across it.
    """

    id: str
    center_lon: float
    center_lat: float
    bbox: dict
    max_power: float
    n_points: int
    point_lon: list[float] = field(default_factory=list)
    point_lat: list[float] = field(default_factory=list)
    axis: str = "EW"
    edge_types: dict = field(default_factory=dict)


def _haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    return haversine_distance_m(lat1, lon1, lat2, lon2) / 1000.0


def _channel_axis(lons: np.ndarray, lats: np.ndarray) -> str:
    """Dominant orientation of a point cluster via PCA ("EW" or "NS").

    The PCA major axis angle is measured from the x-axis (east).  Angles
    within 45 degrees of east/west are classified "EW"; anything steeper is
    "NS".  Degenerate clusters (a single point) default to "EW".
    """
    if len(lons) < 2:
        return "EW"
    x = lons - lons.mean()
    y = lats - lats.mean()
    sxx = float(np.mean(x * x))
    syy = float(np.mean(y * y))
    sxy = float(np.mean(x * y))
    theta = 0.5 * math.atan2(2.0 * sxy, sxx - syy)
    # The major axis is theta; compare its elongation along E-W vs N-S.
    ew = abs(math.cos(theta)) * max(sxx, syy) ** 0.5
    ns = abs(math.sin(theta)) * max(sxx, syy) ** 0.5
    # Account for latitude compression: 1 deg lat is ~1.11x 1 deg lon in km.
    ns *= 1.1
    return "EW" if ew >= ns else "NS"


def cluster_hotspots(
    geojson_path: str,
    *,
    cluster_radius_km: float = 15.0,
    margin_km: float = 10.0,
    max_regions: int = 3,
    channel_buffer_km: float | None = None,
) -> list[HotspotRegion]:
    """Cluster hotspot point features into refinement regions.

    Each region's bounding box is elongated along the dominant channel axis
    (PCA over member points) and extended by ``channel_buffer_km`` beyond the
    cluster on both ends, so the liquid edges (perpendicular to the axis) sit
    in open water on either side of the strait rather than cutting through the
    hotspot itself.
    """
    if channel_buffer_km is None:
        channel_buffer_km = margin_km
    with open(geojson_path) as f:
        gj = json.load(f)
    feats = gj.get("features", [])
    pts = []
    for feat in feats:
        lon, lat = feat["geometry"]["coordinates"]
        power = float(feat["properties"].get("power_density_Wm2", 0.0))
        pts.append((lon, lat, power))
    pts.sort(key=lambda p: p[2], reverse=True)

    regions: list[HotspotRegion] = []
    for lon, lat, power in pts:
        placed = False
        for region in regions:
            if (
                _haversine_km(lon, lat, region.center_lon, region.center_lat)
                <= cluster_radius_km
            ):
                region.point_lon.append(lon)
                region.point_lat.append(lat)
                region.n_points += 1
                region.max_power = max(region.max_power, power)
                placed = True
                break
        if not placed:
            regions.append(
                HotspotRegion(
                    id=f"region-{len(regions) + 1:03d}",
                    center_lon=lon,
                    center_lat=lat,
                    bbox={},
                    max_power=power,
                    n_points=1,
                    point_lon=[lon],
                    point_lat=[lat],
                )
            )

    regions.sort(key=lambda r: r.max_power, reverse=True)
    regions = regions[:max_regions]

    for region in regions:
        lons = np.array(region.point_lon)
        lats = np.array(region.point_lat)
        region.axis = _channel_axis(lons, lats)
        dlon = margin_km / (111.320 * math.cos(math.radians(region.center_lat)))
        dlat = margin_km / 110.540
        # Extra reach along the channel axis so the liquid edges (the two box
        # edges perpendicular to the axis) land in open water.
        buffer_dlon = channel_buffer_km / (
            111.320 * math.cos(math.radians(region.center_lat))
        )
        buffer_dlat = channel_buffer_km / 110.540
        lon_min = float(lons.min() - dlon)
        lon_max = float(lons.max() + dlon)
        lat_min = float(lats.min() - dlat)
        lat_max = float(lats.max() + dlat)
        if region.axis == "EW":
            lon_min -= buffer_dlon
            lon_max += buffer_dlon
        else:
            lat_min -= buffer_dlat
            lat_max += buffer_dlat
        region.edge_types = _edge_types_for_axis(region.axis)
        region.bbox = {
            "lon_min": lon_min,
            "lon_max": lon_max,
            "lat_min": lat_min,
            "lat_max": lat_max,
        }
    return regions


def _edge_types_for_axis(axis: str) -> dict[str, str]:
    """Liquid edges perpendicular to the channel axis."""
    if axis == "EW":
        return {"left": "liquid", "right": "liquid", "top": "solid", "bottom": "solid"}
    return {"left": "solid", "right": "solid", "top": "liquid", "bottom": "liquid"}


def regions_from_sites(sites: list[dict]) -> list[HotspotRegion]:
    """Build regions from explicit strait-site definitions (config override).

    Each site is a mapping with ``id``, ``axis`` ("EW"|"NS") and a ``bbox``
    (``lon_min``, ``lon_max``, ``lat_min``, ``lat_max``).  Explicit sites make
    the refined domains authorable and reproducible — the analyst can align
    the box with the actual strait, ensuring both inlet and outlet liquid
    boundaries sit in open water — instead of relying on inferred hotspot
    clustering.  ``max_power``/``n_points`` are filled from the config when
    provided for reporting.
    """
    regions: list[HotspotRegion] = []
    for idx, site in enumerate(sites, start=1):
        axis = str(site.get("axis", "EW")).upper()
        if axis not in ("EW", "NS"):
            raise ValueError(f"site '{site.get('id')}' has invalid axis '{axis}'")
        bbox = site["bbox"]
        regions.append(
            HotspotRegion(
                id=str(site.get("id", f"region-{idx:03d}")),
                center_lon=0.5 * (bbox["lon_min"] + bbox["lon_max"]),
                center_lat=0.5 * (bbox["lat_min"] + bbox["lat_max"]),
                bbox={
                    "lon_min": float(bbox["lon_min"]),
                    "lon_max": float(bbox["lon_max"]),
                    "lat_min": float(bbox["lat_min"]),
                    "lat_max": float(bbox["lat_max"]),
                },
                max_power=float(site.get("max_power", 0.0)),
                n_points=int(site.get("n_points", 0)),
                axis=axis,
                edge_types=_edge_types_for_axis(axis),
            )
        )
    return regions


def save_regions(regions: list[HotspotRegion], path: str) -> None:
    with open(path, "w") as f:
        json.dump([r.__dict__ for r in regions], f, indent=2)
