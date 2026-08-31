"""Generate static figure assets for the workshop series.

Run from the repo root:
    python3 scripts/generate_workshop_images.py

Writes notebook-relevant figures into docs/workshop/images/.  These back the
markdown image cells in the generated notebooks so the key concept, workflow,
grid, and turbine figures render without executing the notebooks.

The physics and diagram figures are self-contained (numpy + matplotlib); the
turbine fleet curve imports the curated set from src/web/turbines.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyBboxPatch

matplotlib.use("Agg")

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "workshop" / "images"
sys.path.insert(0, str(ROOT / "src"))
from web.turbines import TURBINES, power_kw  # noqa: E402

matplotlib.rcParams.update(
    {
        "font.size": 10,
        "axes.titlesize": 13,
        "axes.labelsize": 10,
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
        "legend.fontsize": 8,
    }
)

NAVY = "#0b3c5d"
TEAL = "#0e7490"
CYAN = "#1aa7c4"
ORANGE = "#f4a261"
CORAL = "#e76f51"
GREY = "#5a707e"
FACE = "#fbfdff"


def save(fig: plt.Figure, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / name, dpi=160, bbox_inches="tight", facecolor=FACE)
    plt.close(fig)
    print(f"wrote {OUT / name}")


def _grid_style(ax: plt.Axes) -> None:
    ax.grid(alpha=0.25, linewidth=0.6)
    ax.spines[["top", "right"]].set_visible(False)


def tidal_superposition() -> None:
    t_h = np.linspace(0.0, 48.0, 2000)
    constituents = [
        ("M2", 0.50, 12.4206012),
        ("S2", 0.20, 12.0),
        ("K1", 0.25, 23.9344696),
        ("O1", 0.15, 25.8193417),
    ]
    eta = np.zeros_like(t_h)
    for _, amp, period in constituents:
        eta += amp * np.cos(2 * np.pi * t_h / period)

    fig, ax = plt.subplots(figsize=(9, 3.2))
    ax.plot(t_h / 24.0, eta, lw=1.4, color=NAVY, label="sum of the 4 constituents")
    colors = [CYAN, ORANGE, CORAL, TEAL]
    for idx, (name, amp, period) in enumerate(constituents):
        ax.plot(
            t_h / 24.0,
            amp * np.cos(2 * np.pi * t_h / period),
            lw=0.7,
            alpha=0.5,
            color=colors[idx],
            label=name,
        )
    ax.set_xlabel("days")
    ax.set_ylabel("η (m)")
    ax.set_title("M2 + S2 + K1 + O1 — two days of elevation")
    ax.legend(loc="upper right", ncol=2)
    _grid_style(ax)
    save(fig, "fig_tidal_superposition.png")


def cubic_power() -> None:
    rho = 1025.0
    u = np.linspace(0.0, 4.0, 200)
    p = 0.5 * rho * u**3

    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    ax.plot(u, p, lw=2.2, color=CORAL)
    for uu in (1.0, 2.0):
        ax.axvline(uu, ls=":", color=GREY, lw=1)
    ax.annotate(
        "U = 2.0 m/s gives 8× the power of U = 1.0 m/s",
        xy=(2.0, 0.5 * rho * 8.0),
        xytext=(1.25, 12500),
        arrowprops=dict(arrowstyle="->", color=NAVY),
        fontsize=8,
        color=NAVY,
    )
    ax.set_xlabel("depth-averaged current speed U (m/s)")
    ax.set_ylabel("power density P (W/m²)")
    ax.set_title("½ρU³ — small speed gains are huge power gains")
    _grid_style(ax)
    save(fig, "fig_cubic_power.png")


def turbine_power_curve() -> None:
    rho, diameter, cp = 1025.0, 20.0, 0.40
    area = np.pi * (diameter / 2) ** 2
    cut_in, rated, cut_out = 0.7, 2.4, 4.0
    p_rated = 0.5 * rho * area * rated**3 * cp

    u = np.linspace(0.0, cut_out + 0.5, 300)
    p = np.where(
        u < cut_in,
        0.0,
        np.where(u < rated, 0.5 * rho * area * u**3 * cp, p_rated),
    )

    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    ax.plot(u, p / 1e3, lw=2.2, color=TEAL)
    ymax = p.max() / 1e3
    for x, label in [(cut_in, "cut-in"), (rated, "rated"), (cut_out, "cut-out")]:
        ax.axvline(x, ls=":", color=GREY, lw=1)
        ax.text(x, 0.06 * ymax, label, ha="center", fontsize=8)
    ax.set_xlabel("current speed U (m/s)")
    ax.set_ylabel("output power (kW)")
    ax.set_title(f"Power curve of a {diameter:.0f} m rotor (Cp = {cp:.2f})")
    _grid_style(ax)
    save(fig, "fig_turbine_power_curve.png")


def spring_neap() -> None:
    t_h = np.linspace(0.0, 30.0 * 24.0, 6000)
    eta = 0.5 * np.cos(2 * np.pi * t_h / 12.4206012) + 0.2 * np.cos(
        2 * np.pi * t_h / 12.0
    )

    fig, ax = plt.subplots(figsize=(9, 3.1))
    ax.plot(t_h / 24.0, eta, lw=0.9, color=CYAN)
    ax.plot(t_h / 24.0, np.abs(eta), lw=1.3, color=CORAL, label="envelope")
    ax.fill_between(t_h / 24.0, -np.abs(eta), np.abs(eta), color=CORAL, alpha=0.12)
    ax.set_xlabel("days")
    ax.set_ylabel("η (m)")
    ax.set_title("M2 + S2 elevation — the spring–neap envelope (14.77 d beat)")
    ax.legend(loc="lower left")
    _grid_style(ax)
    save(fig, "fig_spring_neap.png")


def funnel_effect() -> None:
    verts = [
        (0.2, 2.0),
        (1.0, 2.0),
        (1.5, 1.55),
        (2.0, 1.55),
        (2.7, 2.0),
        (3.5, 2.0),
        (3.5, 1.0),
        (2.7, 1.0),
        (2.0, 1.45),
        (1.5, 1.45),
        (1.0, 1.0),
        (0.2, 1.0),
    ]
    fig, ax = plt.subplots(figsize=(7.6, 3.0))
    ax.add_patch(
        plt.Polygon(verts, closed=True, facecolor="#d8f1f5", edgecolor=TEAL, lw=2)
    )
    arrows = [
        (0.3, 1.8, 0.55, CORAL, 2.0),
        (0.3, 1.5, 0.55, CORAL, 2.0),
        (0.3, 1.2, 0.55, CORAL, 2.0),
        (2.9, 1.85, 0.55, CORAL, 1.4),
        (2.9, 1.5, 0.55, CORAL, 1.4),
        (2.9, 1.15, 0.55, CORAL, 1.4),
    ]
    for x, y, dx, color, lw in arrows:
        ax.annotate(
            "",
            xy=(x + dx, y),
            xytext=(x, y),
            arrowprops=dict(arrowstyle="->", color=color, lw=lw),
        )
    for x, y in ((1.45, 1.76), (1.45, 1.5), (1.45, 1.24)):
        ax.annotate(
            "",
            xy=(x + 0.55, y),
            xytext=(x, y),
            arrowprops=dict(arrowstyle="->", color=NAVY, lw=2.6),
        )
    ax.text(1.75, 2.15, "narrow strait", ha="center", fontsize=9, color=NAVY)
    ax.text(0.55, 2.25, "wide basin", ha="center", fontsize=9, color=GREY)
    ax.text(3.15, 2.25, "wide basin", ha="center", fontsize=9, color=GREY)
    ax.text(
        1.75,
        0.55,
        "Q = A·U — as the cross-sectional area A falls, speed U rises",
        ha="center",
        fontsize=9,
        color=NAVY,
    )
    ax.set_xlim(0.0, 3.7)
    ax.set_ylim(0.4, 2.5)
    ax.axis("off")
    save(fig, "fig_funnel_effect.png")


def _flow_boxes(
    ax, boxes: list[tuple[str, str]], width, height, gap, y, palette
) -> None:
    for i, (title, sub) in enumerate(boxes):
        x = i * (width + gap) + 0.1
        color = palette[i % len(palette)]
        ax.add_patch(
            FancyBboxPatch(
                (x, y),
                width,
                height,
                boxstyle="round,pad=0.03,rounding_size=0.06",
                linewidth=1.6,
                edgecolor=color,
                facecolor=color,
            )
        )
        if len(title) > 18 and " (" in title:
            head, tail = title.split(" (", 1)
            tail = "(" + tail
            ax.text(
                x + width / 2,
                y + height * 0.66,
                head,
                ha="center",
                va="center",
                fontsize=8,
                color="white",
                weight="bold",
            )
            ax.text(
                x + width / 2,
                y + height * 0.40,
                tail,
                ha="center",
                va="center",
                fontsize=8,
                color="white",
                weight="bold",
            )
        else:
            ax.text(
                x + width / 2,
                y + height * 0.62,
                title,
                ha="center",
                va="center",
                fontsize=8,
                color="white",
                weight="bold",
            )
        ax.text(
            x + width / 2,
            y + height * 0.14,
            sub,
            ha="center",
            va="center",
            fontsize=7,
            color="white",
        )
        if i < len(boxes) - 1:
            ax.annotate(
                "",
                xy=(x + width + gap - 0.02, y + height / 2),
                xytext=(x + width + 0.02, y + height / 2),
                arrowprops=dict(arrowstyle="->", color=GREY, lw=1.6),
            )


def screening_cascade() -> None:
    stages = [
        ("Coarse Python model", "Phase A — 2 km Arakawa C-grid"),
        ("Hotspots > 200 W/m²", "hotspots.geojson"),
        ("TELEMAC-2D mesh", "Phase B — unstructured refinement"),
        ("Turbine-array CFD", "actuator-disk modelling"),
        ("Surveys", "geophysical / environmental"),
        ("Pilot deployment", "full-scale device"),
    ]
    fig, ax = plt.subplots(figsize=(7.2, 4.0))
    palette = [CORAL, ORANGE, TEAL, CYAN, NAVY, "#0b3c5d"]
    box_h, box_w, step = 0.46, 4.8, 0.62
    y = 0.0
    for i, (title, sub) in enumerate(stages):
        _flow_boxes(ax, [(title, sub)], box_w, box_h, 0.0, y, [palette[i]])
        if i < len(stages) - 1:
            ax.annotate(
                "",
                xy=(box_w / 2, y + box_h + step - 0.05),
                xytext=(box_w / 2, y + box_h + 0.05),
                arrowprops=dict(arrowstyle="->", color=GREY, lw=1.6),
            )
        y += box_h + step
    ax.set_xlim(0, box_w + 0.2)
    ax.set_ylim(-0.1, y - step + box_h + 0.1)
    ax.axis("off")
    save(fig, "fig_screening_cascade.png")


def pipeline() -> None:
    stages = [
        ("screening (python)", "src.model.run"),
        ("cluster hotspots", "model.telemac prepare"),
        ("TELEMAC-2D (docker)", "telemac2d.py case.cas"),
        ("postprocess", "model.telemac postprocess"),
        ("web (Flask + MapLibre)", "docker compose up"),
    ]
    fig, ax = plt.subplots(figsize=(10.5, 2.8))
    width, height, gap, y = 1.9, 0.8, 0.32, 0.9
    palette = [CORAL, ORANGE, TEAL, CYAN, NAVY]
    _flow_boxes(ax, stages, width, height, gap, y, palette)
    ax.text(
        (5 * (width + gap) - gap) / 2 + 0.1,
        0.32,
        "two engines — one output contract (results.nc, *.tif, hotspots.geojson)",
        ha="center",
        fontsize=9,
        color=GREY,
    )
    ax.set_xlim(0.0, 5 * (width + gap) + 0.2)
    ax.set_ylim(0.0, y + height + 0.25)
    ax.axis("off")
    save(fig, "fig_pipeline.png")


def cgrid() -> None:
    nx, ny = 3, 3
    fig, ax = plt.subplots(figsize=(6.0, 4.6))
    x = np.arange(nx + 1)
    y = np.arange(ny + 1)
    for xi in x:
        ax.plot([xi, xi], [y.min(), y.max()], color="#b6cbd5", lw=1.4, zorder=1)
    for yi in y:
        ax.plot([x.min(), x.max()], [yi, yi], color="#b6cbd5", lw=1.4, zorder=1)
    for i in range(nx):
        for j in range(ny):
            ax.scatter(i + 0.5, j + 0.5, s=90, color=CORAL, zorder=3)
    for i in range(nx + 1):
        for j in range(ny):
            ax.scatter(i, j + 0.5, s=55, color=TEAL, zorder=3)
    for i in range(nx):
        for j in range(ny + 1):
            ax.scatter(i + 0.5, j, s=55, color=ORANGE, zorder=3)
    ax.scatter([], [], s=90, color=CORAL, label="η at cell centres")
    ax.scatter([], [], s=55, color=TEAL, label="u on x-faces")
    ax.scatter([], [], s=55, color=ORANGE, label="v on y-faces")
    ax.set_title("Arakawa C-grid: staggered variables")
    ax.set_xlim(-0.25, nx + 0.25)
    ax.set_ylim(-0.25, ny + 0.25)
    ax.set_aspect("equal")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.06), ncol=3)
    ax.axis("off")
    save(fig, "fig_cgrid.png")


def turbine_fleet() -> None:
    speeds = np.linspace(0.0, 4.8, 160)
    fig, ax = plt.subplots(figsize=(6.8, 4.0))
    colors = plt.cm.viridis(np.linspace(0.08, 0.9, len(TURBINES)))
    for idx, turbine in enumerate(TURBINES):
        values = [power_kw(turbine, float(s)) for s in speeds]
        ax.plot(speeds, values, lw=1.8, color=colors[idx], label=turbine["name"])
    ax.set_xlabel("current speed U (m/s)")
    ax.set_ylabel("electrical output (kW)")
    ax.set_title("Power curves across the curated turbine fleet")
    ax.legend(ncol=2, loc="upper left")
    _grid_style(ax)
    save(fig, "fig_turbine_curves.png")


def main() -> None:
    tidal_superposition()
    cubic_power()
    turbine_power_curve()
    spring_neap()
    funnel_effect()
    screening_cascade()
    pipeline()
    cgrid()
    turbine_fleet()
    print("Done.")


if __name__ == "__main__":
    main()
