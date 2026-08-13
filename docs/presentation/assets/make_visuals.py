"""Generate extra presentation visuals from the tidal-oss outputs."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
matplotlib.rcParams.update(
    {
        "font.size": 15,
        "axes.titlesize": 19,
        "axes.labelsize": 15,
        "xtick.labelsize": 13,
        "ytick.labelsize": 13,
        "legend.fontsize": 12,
    }
)
import matplotlib.pyplot as plt
import numpy as np
import rasterio
from netCDF4 import Dataset

ROOT = Path("/home/bluey/dev/work/tidal-oss")
OUT = ROOT / "docs/presentation/assets"
DATA = ROOT / "output"
sys.path.insert(0, str(ROOT))
from src.web.turbines import TURBINES, power_kw, rated_speed_mps  # noqa: E402


def save(fig: plt.Figure, name: str) -> None:
    fig.savefig(OUT / name, dpi=170, bbox_inches="tight", facecolor="#fbfdff")
    plt.close(fig)


def raster(name: str) -> tuple[np.ndarray, list[float]]:
    with rasterio.open(DATA / name) as src:
        arr = src.read(1).astype(float)
        arr[arr == src.nodata] = np.nan
        bounds = src.bounds
    return arr, [bounds.left, bounds.right, bounds.bottom, bounds.top]


def map_figure(name: str, title: str, label: str, cmap: str, vmax: float | None = None) -> None:
    arr, extent = raster(name)
    fig, ax = plt.subplots(figsize=(8.2, 6.3))
    im = ax.imshow(arr, extent=extent, origin="upper", cmap=cmap, vmax=vmax)
    ax.set_title(title, loc="left", fontsize=15, fontweight="bold", color="#0b3c5d")
    ax.set_xlabel("Longitude (°E)")
    ax.set_ylabel("Latitude (°N)")
    cb = fig.colorbar(im, ax=ax, shrink=0.82, pad=0.02)
    cb.set_label(label)
    ax.grid(color="white", alpha=0.22, linewidth=0.5)
    save(fig, name.replace(".tif", ".png"))


def timeseries_figure() -> None:
    with Dataset(DATA / "results.nc") as nc:
        lat = np.asarray(nc["lat"][:])
        lon = np.asarray(nc["lon"][:])
        time_h = np.asarray(nc["time"][:], dtype=float) / 3600.0
        eta = np.asarray(nc["eta"][:], dtype=float)
        u = np.asarray(nc["u"][:], dtype=float)
        v = np.asarray(nc["v"][:], dtype=float)
        power = np.asarray(nc["power_density"][:], dtype=float)

    peak = np.nanargmax(np.nanmean(power, axis=0))
    row, col = np.unravel_index(peak, power.shape[1:])
    uc = 0.5 * (u[:, row, col] + u[:, row, min(col + 1, u.shape[2] - 1)])
    vc = 0.5 * (v[:, row, col] + v[:, min(row + 1, v.shape[1] - 1), col])
    speed = np.sqrt(uc**2 + vc**2)
    mean_power = np.nanmean(power[:, row, col])

    fig, axes = plt.subplots(3, 1, figsize=(9.0, 3.75), sharex=True)
    color = "#0e7490"
    axes[0].plot(time_h, eta[:, row, col], color="#e76f51", linewidth=2)
    axes[0].set_ylabel("η (m)")
    axes[0].set_title(
        f"Model time series at energetic cell {lon[row, col]:.2f}°E, {lat[row, col]:.2f}°N",
        loc="left", fontsize=18, fontweight="bold", color="#0b3c5d",
    )
    axes[1].plot(time_h, speed, color=color, linewidth=2)
    axes[1].set_ylabel("Speed (m/s)")
    axes[2].plot(time_h, power[:, row, col], color="#f4a261", linewidth=2)
    axes[2].axhline(200, color="#e76f51", linestyle="--", linewidth=1.2, label="200 W/m² screen")
    axes[2].set_ylabel("Power (W/m²)")
    axes[2].set_xlabel("Simulation time (hours)")
    axes[2].legend(frameon=False, fontsize=13, loc="upper right")
    for ax in axes:
        ax.grid(alpha=0.2)
        ax.spines[["top", "right"]].set_visible(False)
    fig.text(0.98, 0.02, f"Mean power density: {mean_power:.1f} W/m²", ha="right", color="#5a707e", fontsize=13)
    save(fig, "fig_timeseries.png")


def turbine_figure() -> None:
    speeds = np.linspace(0, 4.8, 160)
    fig, ax = plt.subplots(figsize=(5.2, 3.4))
    colors = plt.cm.viridis(np.linspace(0.05, 0.92, len(TURBINES)))
    for turbine, color in zip(TURBINES, colors):
        values = [power_kw(turbine, float(speed)) for speed in speeds]
        ax.plot(speeds, values, color=color, linewidth=2.2, label=turbine["name"])
    ax.set_title("Power curves across the curated turbine fleet", loc="left", fontsize=18, fontweight="bold", color="#0b3c5d")
    ax.set_xlabel("Current speed (m/s)")
    ax.set_ylabel("Electrical output (kW)")
    ax.grid(alpha=0.2)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(ncol=2, fontsize=12, frameon=False, loc="upper left")
    save(fig, "fig_turbine_curves.png")

    rated = [t["rated_power_kw"] for t in TURBINES]
    rated_speeds = [rated_speed_mps(t) for t in TURBINES]
    labels = [t["name"] for t in TURBINES]
    order = np.argsort(rated)
    fig, ax = plt.subplots(figsize=(5.2, 3.2))
    bars = ax.barh(np.array(labels)[order], np.array(rated)[order], color="#0e7490")
    for bar, speed in zip(bars, np.array(rated_speeds)[order]):
        ax.text(bar.get_width() + 35, bar.get_y() + bar.get_height() / 2, f"{speed:.2f} m/s", va="center", fontsize=11)
    ax.set_title("Rated power and derived rated speed", loc="left", fontsize=18, fontweight="bold", color="#0b3c5d")
    ax.set_xlabel("Rated power (kW)")
    ax.grid(axis="x", alpha=0.2)
    ax.spines[["top", "right"]].set_visible(False)
    save(fig, "fig_turbine_fleet.png")


def physics_figures() -> None:
    # A conceptual harmonic reconstruction and spring-neap envelope.
    hours = np.linspace(0, 24 * 15, 1200)
    m2 = np.sin(2 * np.pi * hours / 12.42)
    s2 = 0.35 * np.sin(2 * np.pi * hours / 12.0)
    combined = m2 + s2
    fig, axes = plt.subplots(2, 1, figsize=(6.5, 4.1), sharex=True)
    axes[0].plot(hours, m2, label="M₂ · 12.42 h", color="#0e7490")
    axes[0].plot(hours, s2, label="S₂ · 12.00 h", color="#f4a261")
    axes[0].plot(hours, combined, label="combined tide", color="#0b3c5d", linewidth=2)
    axes[0].set_ylabel("Relative elevation")
    axes[0].legend(ncol=3, frameon=False, fontsize=11)
    axes[1].plot(hours, np.abs(combined), color="#e76f51", linewidth=1.8)
    axes[1].fill_between(hours, np.abs(combined), color="#e76f51", alpha=0.16)
    axes[1].axvspan(0, 24 * 3.7, color="#f4a261", alpha=0.10, label="spring tide")
    axes[1].axvspan(24 * 7.3, 24 * 11.0, color="#1aa7c4", alpha=0.08, label="neap transition")
    axes[1].set_ylabel("Current envelope")
    axes[1].set_xlabel("Days since start")
    axes[1].legend(frameon=False, fontsize=11, loc="upper right")
    for ax in axes:
        ax.grid(alpha=0.2)
        ax.spines[["top", "right"]].set_visible(False)
    axes[0].set_title("Tidal constituents beat into a 14.77-day spring–neap cycle", loc="left", fontsize=17, fontweight="bold", color="#0b3c5d")
    save(fig, "fig_spring_neap.png")

    speeds = np.linspace(0, 3.2, 160)
    power = 0.5 * 1025.0 * speeds**3
    fig, ax = plt.subplots(figsize=(6.0, 3.75))
    ax.plot(speeds, power, color="#e76f51", linewidth=3)
    for speed in (1.0, 2.0, 3.0):
        value = 0.5 * 1025.0 * speed**3
        ax.scatter([speed], [value], color="#0b3c5d", zorder=3)
        ax.annotate(f"{speed:.0f} m/s\n{value:.0f} W/m²", (speed, value), xytext=(8, 8), textcoords="offset points", fontsize=12)
    ax.set_title("Why current speed matters: power scales with U³", loc="left", fontsize=18, fontweight="bold", color="#0b3c5d")
    ax.set_xlabel("Current speed U (m/s)")
    ax.set_ylabel("Theoretical power density (W/m²)")
    ax.grid(alpha=0.2)
    ax.spines[["top", "right"]].set_visible(False)
    save(fig, "fig_cubic_power.png")


def write_diagrams() -> None:
    (OUT / "fig_cgrid.svg").write_text(
        """<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 760 430'>
<rect width='760' height='430' rx='18' fill='#fbfdff'/>
<text x='34' y='44' font-family='Arial' font-size='29' font-weight='700' fill='#0b3c5d'>Arakawa C-grid: staggered variables</text>
<g stroke='#b6cbd5' stroke-width='2' fill='none'>
<path d='M120 110H600M120 190H600M120 270H600M120 350H600M120 110V350M280 110V350M440 110V350M600 110V350'/></g>
<g fill='#e76f51'><circle cx='200' cy='150' r='10'/><circle cx='360' cy='150' r='10'/><circle cx='520' cy='150' r='10'/><circle cx='200' cy='230' r='10'/><circle cx='360' cy='230' r='10'/><circle cx='520' cy='230' r='10'/><circle cx='200' cy='310' r='10'/><circle cx='360' cy='310' r='10'/><circle cx='520' cy='310' r='10'/></g>
<g fill='#0e7490'><circle cx='120' cy='150' r='8'/><circle cx='280' cy='150' r='8'/><circle cx='440' cy='150' r='8'/><circle cx='600' cy='150' r='8'/><circle cx='120' cy='230' r='8'/><circle cx='280' cy='230' r='8'/><circle cx='440' cy='230' r='8'/><circle cx='600' cy='230' r='8'/></g>
<g fill='#f4a261'><circle cx='200' cy='110' r='8'/><circle cx='360' cy='110' r='8'/><circle cx='520' cy='110' r='8'/><circle cx='200' cy='190' r='8'/><circle cx='360' cy='190' r='8'/><circle cx='520' cy='190' r='8'/><circle cx='200' cy='270' r='8'/><circle cx='360' cy='270' r='8'/><circle cx='520' cy='270' r='8'/><circle cx='200' cy='350' r='8'/><circle cx='360' cy='350' r='8'/><circle cx='520' cy='350' r='8'/></g>
<text x='625' y='155' font-family='Arial' font-size='22' fill='#0e7490'>u-face</text><text x='625' y='195' font-family='Arial' font-size='22' fill='#f4a261'>v-face</text><text x='625' y='235' font-family='Arial' font-size='22' fill='#e76f51'>η centre</text>
<text x='34' y='405' font-family='Arial' font-size='19' fill='#5a707e'>Velocity components live on faces; free-surface elevation lives at cell centres.</text></svg>""",
        encoding="utf-8",
    )
    (OUT / "fig_mcda.svg").write_text(
        """<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 900 270'><rect width='900' height='270' rx='18' fill='#fbfdff'/><text x='35' y='40' font-family='Arial' font-size='28' font-weight='700' fill='#0b3c5d'>From resource to a defensible site decision</text><g font-family='Arial' font-size='20' text-anchor='middle'><rect x='35' y='95' width='170' height='80' rx='12' fill='#fdf9f0' stroke='#f4a261' stroke-width='3'/><text x='120' y='130'>Resource</text><text x='120' y='153'>assessment</text><rect x='255' y='95' width='170' height='80' rx='12' fill='#edf6f9' stroke='#1aa7c4' stroke-width='3'/><text x='340' y='130'>Constraints</text><text x='340' y='153'>physical · social · eco</text><rect x='475' y='95' width='170' height='80' rx='12' fill='#fdf5f1' stroke='#e76f51' stroke-width='3'/><text x='560' y='130'>Suitability</text><text x='560' y='153'>standardise + weight</text><rect x='695' y='95' width='170' height='80' rx='12' fill='#0b3c5d'/><text x='780' y='130' fill='white'>Site–device</text><text x='780' y='153' fill='white'>match + rank</text></g><g stroke='#7f9aa8' stroke-width='3' fill='none'><path d='M205 135h45'/><path d='M425 135h45'/><path d='M645 135h45'/></g></svg>""",
        encoding="utf-8",
    )
    (OUT / "fig_roadmap.svg").write_text(
        """<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 900 250'><rect width='900' height='250' rx='18' fill='#fbfdff'/><text x='35' y='38' font-family='Arial' font-size='28' font-weight='700' fill='#0b3c5d'>Open development roadmap</text><g font-family='Arial' font-size='20' text-anchor='middle'><rect x='35' y='88' width='180' height='80' rx='12' fill='#0b3c5d'/><text x='125' y='122' fill='white'>Screening</text><text x='125' y='146' fill='white'>~2 km model</text><rect x='255' y='88' width='180' height='80' rx='12' fill='#0e7490'/><text x='345' y='122' fill='white'>Refinement</text><text x='345' y='146' fill='white'>TELEMAC-2D</text><rect x='475' y='88' width='180' height='80' rx='12' fill='#1aa7c4'/><text x='565' y='122' fill='white'>Forecasting</text><text x='565' y='146' fill='white'>live boundaries</text><rect x='695' y='88' width='170' height='80' rx='12' fill='#e76f51'/><text x='780' y='122' fill='white'>Investment</text><text x='780' y='146' fill='white'>economic MCDA</text></g><g stroke='#7f9aa8' stroke-width='3'><path d='M215 128h40'/><path d='M435 128h40'/><path d='M655 128h40'/></g></svg>""",
        encoding="utf-8",
    )
    (OUT / "fig_tidal_forcing.svg").write_text(
        """<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 900 330'><rect width='900' height='330' rx='18' fill='#fbfdff'/><text x='35' y='42' font-family='Arial' font-size='25' font-weight='700' fill='#0b3c5d'>Tides begin as astronomical forcing</text><circle cx='170' cy='175' r='55' fill='#f4a261'/><text x='170' y='181' text-anchor='middle' font-family='Arial' font-size='18' font-weight='700' fill='#3a2c00'>SUN</text><circle cx='700' cy='175' r='38' fill='#b7cbd4'/><text x='700' y='181' text-anchor='middle' font-family='Arial' font-size='15' font-weight='700' fill='#0b3c5d'>MOON</text><ellipse cx='440' cy='175' rx='105' ry='70' fill='#1aa7c4' stroke='#0b3c5d' stroke-width='4'/><text x='440' y='181' text-anchor='middle' font-family='Arial' font-size='18' font-weight='700' fill='white'>EARTH</text><path d='M230 145 Q320 95 350 130' fill='none' stroke='#e76f51' stroke-width='5' marker-end='url(#a)'/><path d='M550 130 Q620 90 660 145' fill='none' stroke='#e76f51' stroke-width='5' marker-end='url(#a)'/><path d='M230 205 Q320 255 350 220' fill='none' stroke='#e76f51' stroke-width='5' marker-end='url(#a)'/><path d='M550 220 Q620 260 660 205' fill='none' stroke='#e76f51' stroke-width='5' marker-end='url(#a)'/><defs><marker id='a' markerWidth='10' markerHeight='10' refX='8' refY='3' orient='auto'><path d='M0,0 L8,3 L0,6z' fill='#e76f51'/></marker></defs><text x='440' y='300' text-anchor='middle' font-family='Arial' font-size='17' fill='#5a707e'>Astronomical forcing → changing sea level → pressure gradients → currents</text></svg>""",
        encoding="utf-8",
    )
    (OUT / "fig_energy_conversion.svg").write_text(
        """<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 900 280'><rect width='900' height='280' rx='18' fill='#fbfdff'/><text x='35' y='42' font-family='Arial' font-size='25' font-weight='700' fill='#0b3c5d'>From moving water to electricity</text><g font-family='Arial' font-size='17' text-anchor='middle'><rect x='35' y='105' width='145' height='78' rx='13' fill='#0e7490'/><text x='107' y='138' fill='white'>Tidal flow</text><text x='107' y='161' fill='white'>½ρU³</text><rect x='220' y='105' width='145' height='78' rx='13' fill='#1aa7c4'/><text x='292' y='138' fill='white'>Rotor</text><text x='292' y='161' fill='white'>lift + torque</text><rect x='405' y='105' width='145' height='78' rx='13' fill='#f4a261'/><text x='477' y='138'>Shaft</text><text x='477' y='161'>rotation</text><rect x='590' y='105' width='145' height='78' rx='13' fill='#e76f51'/><text x='662' y='138' fill='white'>Generator</text><text x='662' y='161' fill='white'>electricity</text><rect x='775' y='105' width='90' height='78' rx='13' fill='#0b3c5d'/><text x='820' y='150' fill='white'>GRID</text></g><g stroke='#7f9aa8' stroke-width='3'><path d='M180 144h40'/><path d='M365 144h40'/><path d='M550 144h40'/><path d='M735 144h40'/></g><text x='450' y='235' text-anchor='middle' font-family='Arial' font-size='16' fill='#5a707e'>The resource model estimates the flow; the turbine model estimates useful electrical yield.</text></svg>""",
        encoding="utf-8",
    )
    (OUT / "fig_funnel_effect.svg").write_text(
        """<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 900 300'><rect width='900' height='300' rx='18' fill='#fbfdff'/><text x='35' y='40' font-family='Arial' font-size='25' font-weight='700' fill='#0b3c5d'>Why straits accelerate tidal currents</text><path d='M35 90H330L480 140L630 90H865V250H630L480 200L330 250H35z' fill='#d8f1f5' stroke='#0e7490' stroke-width='3'/><g stroke='#e76f51' stroke-width='5'><path d='M75 130h120'/><path d='M75 175h120'/><path d='M735 130h100'/><path d='M735 175h100'/><path d='M270 150h150'/><path d='M540 150h150'/></g><g fill='#0b3c5d' font-family='Arial' font-size='17' text-anchor='middle'><text x='175' y='115'>wide basin</text><text x='480' y='125'>narrow strait</text><text x='785' y='115'>wide basin</text></g><text x='480' y='280' text-anchor='middle' font-family='Arial' font-size='17' fill='#5a707e'>Q = A·U: when cross-sectional area A falls, current speed U rises</text></svg>""",
        encoding="utf-8",
    )
    # Keep labels legible when the diagrams are projected at presentation scale.
    for name, sizes in {
        "fig_tidal_forcing.svg": {"25": "29", "18": "22", "15": "19", "17": "20"},
        "fig_energy_conversion.svg": {"25": "29", "17": "21", "16": "19"},
        "fig_funnel_effect.svg": {"25": "29", "17": "21"},
    }.items():
        path = OUT / name
        text = path.read_text(encoding="utf-8")
        for old, new in sizes.items():
            text = text.replace(f"font-size='{old}'", f"font-size='{new}'")
        path.write_text(text, encoding="utf-8")


def main() -> None:
    map_figure("distance_to_coast.tif", "Distance-to-coast constraint layer", "Distance (km)", "magma")
    timeseries_figure()
    turbine_figure()
    physics_figures()
    write_diagrams()
    print("Generated additional presentation visuals")


if __name__ == "__main__":
    main()
