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


@dataclass
class HotspotRegion:
    """A clustered, margin-expanded refinement region."""

    id: str
    center_lon: float
    center_lat: float
    bbox: dict
    max_power: float
    n_points: int
    point_lon: list[float] = field(default_factory=list)
    point_lat: list[float] = field(default_factory=list)


def _haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def cluster_hotspots(
    geojson_path: str,
    *,
    cluster_radius_km: float = 15.0,
    margin_km: float = 10.0,
    max_regions: int = 3,
) -> list[HotspotRegion]:
    """Cluster hotspot point features into refinement regions."""
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
        dlon = margin_km / (111.320 * math.cos(math.radians(region.center_lat)))
        dlat = margin_km / 110.540
        region.bbox = {
            "lon_min": float(lons.min() - dlon),
            "lon_max": float(lons.max() + dlon),
            "lat_min": float(lats.min() - dlat),
            "lat_max": float(lats.max() + dlat),
        }
    return regions


def save_regions(regions: list[HotspotRegion], path: str) -> None:
    with open(path, "w") as f:
        json.dump([r.__dict__ for r in regions], f, indent=2)
