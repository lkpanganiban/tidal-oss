"""Render figures for the FOSS4G presentation from the tidal-oss outputs."""
import json
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import rasterio
from rasterio.plot import show as rio_show

OUT = "/home/bluey/dev/work/tidal-oss/docs/presentation/assets"
DATA = "/home/bluey/dev/work/tidal-oss/output"

# domain extent (Philippines bounding box)
LON = (116.0, 130.0)
LAT = (4.0, 22.0)
EXTENT = [LON[0], LON[1], LAT[0], LAT[1]]

LAND = "#c8b69b"
SEA_CMAP = "Blues"
PD_CMAP = "hot_r"


def base_axes(ax, title):
    ax.set_xlim(EXTENT[0], EXTENT[1])
    ax.set_ylim(EXTENT[2], EXTENT[3])
    ax.set_title(title, fontsize=15, fontweight="bold", pad=10)
    ax.set_xlabel("Longitude (\u00b0E)", fontsize=11)
    ax.set_ylabel("Latitude (\u00b0N)", fontsize=11)
    ax.set_aspect(1.0 / np.cos(np.deg2rad(13.0)))


# ----------------------------------------------------------------------
# 1. Bathymetry
# ----------------------------------------------------------------------
with rasterio.open(f"{DATA}/bathymetry.tif") as ds:
    bathy = ds.read(1).astype(float)
    bathy[bathy < -10000] = np.nan

fig, ax = plt.subplots(figsize=(10.5, 8.5), dpi=150)
base_axes(ax, "Bathymetry (m) \u2014 GEBCO regridded to ~2 km Arakawa C-grid")
cmap = mcolors.LinearSegmentedColormap.from_list(
    "deep", ["#08306b", "#08519c", "#2171b5", "#6baed6", "#c6dbef", "#e8dcc8", "#b09868"]
)
norm = mcolors.TwoSlopeNorm(vmin=-6000, vcenter=-200, vmax=200)
im = ax.imshow(bathy, extent=EXTENT, origin="upper", cmap=cmap, norm=norm)
bathy_masked = np.ma.masked_invalid(bathy)
mask = np.isnan(bathy)
# land (elevation >= 0) shown as land colour
land = np.where((bathy >= 0) & ~mask, 1.0, np.nan)
ax.imshow(land, extent=EXTENT, origin="upper", cmap=mcolors.ListedColormap([LAND]), alpha=0.95)
cb = fig.colorbar(im, ax=ax, shrink=0.82, pad=0.02)
cb.set_label("Elevation (m, + land / \u2212 sea)", fontsize=11)
fig.tight_layout()
fig.savefig(f"{OUT}/fig_bathymetry.png", bbox_inches="tight")
plt.close(fig)
print("fig_bathymetry.png done")

# ----------------------------------------------------------------------
# 2. Tidal power density + hotspots
# ----------------------------------------------------------------------
with rasterio.open(f"{DATA}/tidal_power_density.tif") as ds:
    pd = ds.read(1).astype(float)
    pd[pd < 0] = np.nan
    pd[pd > 2000] = 2000

fig, ax = plt.subplots(figsize=(10.5, 8.5), dpi=150)
base_axes(ax, "Time-mean tidal power density  P = \u00bd\u03c1|U|\u00b3  (W/m\u00b2) with hotspots \u2265 200 W/m\u00b2")
pd_mask = np.isfinite(pd)
im = ax.imshow(np.where(pd_mask, pd, np.nan), extent=EXTENT, origin="upper",
               cmap=PD_CMAP, vmin=0, vmax=1000)
ax.imshow(np.where((bathy >= 0) & ~mask, 1.0, np.nan), extent=EXTENT, origin="upper",
          cmap=mcolors.ListedColormap([LAND]), alpha=0.95, zorder=2)

with open(f"{DATA}/hotspots.geojson") as f:
    gj = json.load(f)
feats = gj["features"]
coords_list = []
for feat in feats:
    g = feat["geometry"]
    gtype = g["type"]
    raw = g["coordinates"]
    if gtype == "Polygon":
        coords_list.append(np.asarray(raw[0]))
    elif gtype == "MultiPolygon":
        for ring in raw:
            coords_list.append(np.asarray(ring[0]))
    elif gtype == "LineString":
        coords_list.append(np.asarray(raw))
    elif gtype == "MultiLineString":
        for line in raw:
            coords_list.append(np.asarray(line))
    elif gtype == "Point":
        coords_list.append(np.asarray([raw]))
    elif gtype == "MultiPoint":
        for p in raw:
            coords_list.append(np.asarray([p]))

for c in coords_list:
    if len(c) == 1:
        ax.plot(c[0][0], c[0][1], "r*", ms=12, mew=0, zorder=4)
    else:
        ax.plot(c[:, 0], c[:, 1], color="red", lw=1.6, zorder=4)
cb = fig.colorbar(im, ax=ax, shrink=0.82, pad=0.02)
cb.set_label("Mean power density (W/m\u00b2)", fontsize=11)
fig.tight_layout()
fig.savefig(f"{OUT}/fig_power_hotspots.png", bbox_inches="tight")
plt.close(fig)
print("fig_power_hotspots.png done  (hotspot features:", len(feats), ")")

# ----------------------------------------------------------------------
# 3. Max current speed
# ----------------------------------------------------------------------
with rasterio.open(f"{DATA}/max_current_speed.tif") as ds:
    spd = ds.read(1).astype(float)
    spd[spd < 0] = np.nan

fig, ax = plt.subplots(figsize=(10.5, 8.5), dpi=150)
base_axes(ax, "Maximum current speed (m/s)")
im = ax.imshow(np.where(np.isfinite(spd), spd, np.nan), extent=EXTENT, origin="upper",
               cmap="viridis", vmin=0, vmax=2.5)
ax.imshow(np.where((bathy >= 0) & ~mask, 1.0, np.nan), extent=EXTENT, origin="upper",
          cmap=mcolors.ListedColormap([LAND]), alpha=0.95, zorder=2)
cb = fig.colorbar(im, ax=ax, shrink=0.82, pad=0.02)
cb.set_label("Max current speed (m/s)", fontsize=11)
fig.tight_layout()
fig.savefig(f"{OUT}/fig_max_speed.png", bbox_inches="tight")
plt.close(fig)
print("fig_max_speed.png done")
print("ALL DONE")
