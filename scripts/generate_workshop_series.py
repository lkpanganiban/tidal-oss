"""Generate the consolidated workshop series under docs/workshop/.

Run from the repo root:
    python3 scripts/generate_workshop_series.py

Writes:
    docs/workshop/README.md              index (also produced by this script)
    docs/workshop/0.setup.ipynb          environment, install, data setup
    docs/workshop/1.concept.ipynb        tidal physics and resource concepts
    docs/workshop/2.data.ipynb           inputs, config, canonical outputs
    docs/workshop/3.general-workflow.ipynb  end-to-end pipeline
    docs/workshop/4.model.ipynb          hands-on screening model
    docs/workshop/5.web.ipynb            web service and API
    docs/workshop/6.consolidation.ipynb  recap, exercises, further reading
    docs/workshop/site/index.html  single-page HTML view (via
                                   scripts/build_workshop_website.py)

The series consolidates the standalone docs (docs/concepts, docs/architecture,
docs/engines, docs/operations) into a linear, runnable workshop path.  Code
cells are defensive: they degrade gracefully when optional packages or
generated outputs are unavailable.
"""

from __future__ import annotations

import json
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "docs" / "workshop"

REPO_ROOT = Path(__file__).resolve().parent.parent


def notebook(cells: list[dict]) -> dict:
    return {
        "cells": cells,
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {"name": "python", "version": "3.12"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def md(text: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": text}


def code(text: str) -> dict:
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": text,
    }


def img(path: str, caption: str) -> dict:
    """A markdown cell that embeds a static figure from images/."""
    return md(f"![{caption}](images/{path})\n")


def nav(prev: str | None = None, nxt: str | None = None) -> str:
    """Series footer: links to the index and the previous/next notebook."""
    links = ["[Index](README.md)"]
    if prev:
        links.append(f"[← {prev}]({prev})")
    if nxt:
        links.append(f"[{nxt} →]({nxt})")
    return "\n\n---\n\n" + " · ".join(links) + "\n"


def header(kicker: str, title: str, blurb: str) -> str:
    return f"# {kicker} — {title}\n\n{blurb}\n"


def _write(name: str, cells: list[dict]) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / name
    with path.open("w", encoding="utf-8") as fh:
        json.dump(notebook(cells), fh, indent=1, ensure_ascii=False)
    print(f"wrote {path} ({len(cells)} cells)")
    return path


# ---------------------------------------------------------------------------
# 0. setup
# ---------------------------------------------------------------------------
def n_setup() -> list[dict]:
    return [
        md(
            header(
                "Notebook 0",
                "Setup: environment, install, and data",
                "Get the repository running so the rest of the workshop has "
                "something to build on. You will verify the Python environment, "
                "install the packages, and check that the input data is in place. "
                "Detailed setup is also in `../../src/README.md`.",
            )
        ),
        md(
            "## Learning objectives\n"
            "\n"
            "- Confirm Python 3.10+ and the core scientific packages.\n"
            "- Make the `model` and `web` packages importable.\n"
            "- Download or locate the external datasets referenced by "
            "`src/model/config.yaml`.\n"
            "- Verify the screening configuration loads.\n"
        ),
        md(
            "## 0.1 Python version\n"
            "\n"
            "The project requires Python 3.10 or newer. The intended "
            "environment is documented in `../AGENTS.md`; it is a dedicated "
            "conda environment with numpy, scipy, rasterio, netCDF4, xarray, "
            "numba, and matplotlib.\n"
        ),
        code(
            "import platform\n"
            "import sys\n"
            "\n"
            "print('Python', sys.version.split()[0], '|', platform.platform())\n"
        ),
        md(
            "## 0.2 Install the packages\n"
            "\n"
            "From the repository root:\n"
            "\n"
            "```bash\n"
            "python -m venv .venv && source .venv/bin/activate\n"
            "pip install -e .\n"
            "pip install -r src/requirements-lock.txt\n"
            "# development extras (optional):\n"
            "pip install -r src/requirements-dev.txt\n"
            "```\n"
            "\n"
            "An editable install (`pip install -e .`) puts `model` and `web` "
            "on the import path, so the notebooks below work without setting "
            "`PYTHONPATH`. If you prefer not to install, export `PYTHONPATH=src` "
            "before starting Jupyter.\n"
        ),
        code(
            "try:\n"
            "    from model.grid import StructuredGrid\n"
            "    from model.solver import ShallowWaterSolver\n"
            "    from model.forcing import make_synthetic_tidal_boundary\n"
            "    from model.utils import speed, power_density\n"
            "    from model.config import load_config\n"
            "    from model.output import NetCDFStreamWriter\n"
            "    print('model package: OK')\n"
            "except ImportError as exc:\n"
            "    print('model package not importable:', exc)\n"
            "    print('Run:  pip install -e .   or   export PYTHONPATH=src')\n"
            "\n"
            "for pkg in ('numpy', 'scipy', 'matplotlib', 'rasterio', 'netCDF4', 'xarray'):\n"
            "    try:\n"
            "        mod = __import__(pkg)\n"
            "        print(f'{pkg:<12s}', getattr(mod, '__version__', '?'))\n"
            "    except ImportError:\n"
            "        print(f'{pkg:<12s} MISSING')\n"
        ),
        md(
            "## 0.3 Download the data\n"
            "\n"
            "The model can run on synthetic data with no files, but a realistic "
            "study needs external datasets:\n"
            "\n"
            "| Dataset | Used for | How to get it |\n"
            "|---------|----------|---------------|\n"
            "| **GEBCO 2026** NetCDF | Bathymetry | `python downloader.py --gebco` (auto) |\n"
            "| **GOT4.10c** harmonics | Tidal forcing | `python downloader.py --tidal` (auto) |\n"
            "| **Philippines landmass GeoJSON** | Land mask | `python downloader.py --landmask` (auto) |\n"
            "| FES2014 / TPXO9 | Alternative forcing | Manual (registration; see `../../src/README.md`) |\n"
            "\n"
            "```bash\n"
            "python downloader.py --all\n"
            "```\n"
            "\n"
            "`--all` auto-downloads the GEBCO subset, the GeoBoundaries "
            "landmask, and GOT4.10c, and prints the manual steps for FES2014 "
            "and TPXO9. Files already present are skipped.\n"
        ),
        md(
            "## 0.4 Verify the configuration\n"
            "\n"
            "`src/model/config.yaml` is the single source of truth for the "
            "screening run. Let's print the key sections and check the working "
            "directories exist.\n"
        ),
        code(
            "import json\n"
            "from pathlib import Path\n"
            "\n"
            "try:\n"
            "    from model.config import load_config\n"
            "    cfg = load_config()\n"
            "    print(json.dumps({\n"
            "        'domain': cfg['domain'],\n"
            "        'simulation': cfg['simulation'],\n"
            "        'tidal_forcing': cfg['tidal_forcing'],\n"
            "        'output': cfg['output'],\n"
            "        'engine': cfg['engine'],\n"
            "    }, indent=2, default=str))\n"
            "except Exception as exc:\n"
            "    print('config could not be loaded:', exc)\n"
            "\n"
            "print('\\n--- directories ---')\n"
            "for name in ('data', 'output', 'cases'):\n"
            "    print(('exists ' if Path(name).exists() else 'missing'), name)\n"
        ),
        md(
            "## 0.5 Conda quick tour (recommended)\n"
            "\n"
            "The project is developed and tested in a dedicated **conda** "
            "environment named `tidaloss` (see `../AGENTS.md`). Conda bundles "
            "the compiled scientific stack — rasterio, netCDF4, numba — that "
            "plain `pip` wheels frequently struggle with, so it is the "
            "recommended way to reproduce this setup. Create and activate the "
            "environment, then follow § 0.2 for the pip installs:\n"
            "\n"
            "```bash\n"
            "conda create -n tidaloss python=3.12\n"
            "conda activate tidaloss\n"
            "# now run the pip install commands from § 0.2\n"
            "```\n"
            "\n"
            "Every shell command in this workshop runs inside the activated "
            "environment. Common conda commands:\n"
            "\n"
            "| Command | Purpose |\n"
            "|---------|---------|\n"
            "| `conda create -n tidaloss python=3.12` | Create a new environment with a Python version |\n"
            "| `conda activate tidaloss` / `conda deactivate` | Enter / leave the environment |\n"
            "| `conda env list` | List all environments and their paths |\n"
            "| `conda list` | Show packages installed in the active environment |\n"
            "| `conda install numpy` | Install or update a package |\n"
            "| `conda env export > environment.yml` | Snapshot the environment for sharing / backup |\n"
            "| `conda env create -f environment.yml` | Recreate an environment from a snapshot |\n"
            "\n"
            "The cell below only reports the conda version and environments; it "
            "does not create anything.\n"
        ),
        code(
            "import shutil\n"
            "import subprocess\n"
            "\n"
            "if shutil.which('conda'):\n"
            "    try:\n"
            "        r = subprocess.run(['conda', '--version'],\n"
            "                           capture_output=True, text=True, timeout=20)\n"
            "        print((r.stdout or r.stderr).strip())\n"
            "        r = subprocess.run(['conda', 'env', 'list'],\n"
            "                           capture_output=True, text=True, timeout=20)\n"
            "        print((r.stdout or r.stderr).strip())\n"
            "    except Exception as exc:\n"
            "        print('conda check failed:', exc)\n"
            "else:\n"
            "    print('conda not found on PATH (install Miniforge/Miniconda)')\n"
        ),
        md(
            "## 0.6 Docker quick tour (optional)\n"
            "\n"
            "Docker is used for the two parts of the stack that are impractical "
            "to install natively:\n"
            "\n"
            "- the **web service** (Flask + MapLibre map) ships as an image built "
            "from `src/Dockerfile` and run via `docker compose`;\n"
            "- the **TELEMAC-2D refinement engine** runs *only* inside a pinned "
            "public Docker image (`flussplan/telemac:v8-latest` by default, see "
            "`src/model/config.yaml`), so the repo never compiles it.\n"
            "\n"
            "An image is a frozen snapshot of a filesystem; a container is a "
            "running instance of it. `docker compose` turns `docker-compose.yml` "
            "into one-command workflows. The commands this repo actually uses:\n"
            "\n"
            "| Command | Purpose |\n"
            "|---------|---------|\n"
            "| `docker compose up -d --build` | Build + start the web service at http://localhost:8001 |\n"
            "| `docker compose ps` | Show container status |\n"
            "| `docker compose logs -f tidal-web` | Follow the web service logs |\n"
            "| `docker compose down` | Stop the containers (output data persists on disk) |\n"
            "| `docker build -t tidal-model -f src/Dockerfile .` | Build the web image by hand |\n"
            '| `docker run -p 5000:5000 -v "$(pwd)/output:/output" tidal-model` | Run the image directly (map port 5000, mount outputs) |\n'
            "| `docker image ls` | List local images |\n"
            "| `docker ps -a` | List running / stopped containers |\n"
            "\n"
            "The cell below only reports availability; it does not start a "
            "container.\n"
        ),
        code(
            "import shutil\n"
            "import subprocess\n"
            "\n"
            "if shutil.which('docker'):\n"
            "    try:\n"
            "        r = subprocess.run(['docker', 'compose', 'version'],\n"
            "                           capture_output=True, text=True, timeout=20)\n"
            "        print((r.stdout or r.stderr).strip())\n"
            "    except Exception as exc:\n"
            "        print('docker compose check failed:', exc)\n"
            "else:\n"
            "    print('docker not found on PATH (needed for the web + TELEMAC steps)')\n"
        ),
        md(
            "## Next\n"
            "\n"
            "Environment is ready. Move to "
            "[Notebook 1 — concept](1.concept.ipynb) for the physics behind the "
            "resource estimate." + nav(prev="README.md", nxt="1.concept.ipynb"),
        ),
    ]


# ---------------------------------------------------------------------------
# 1. concept
# ---------------------------------------------------------------------------
def n_concept() -> list[dict]:
    return [
        md(
            header(
                "Notebook 1",
                "Concept: why tidal currents carry energy",
                "Before running any code we need to be clear about what the model "
                "computes and why. This notebook explains the physics behind the "
                "resource estimate: where tides come from, how the free surface is "
                "reconstructed from harmonic constituents, how elevation is turned "
                "into a current by the shallow-water equations, and why the "
                "resulting kinetic-energy flux is what a tidal-stream turbine "
                "cares about. Each idea is accompanied by a small code check you "
                "can run and modify. The full derivation and methodology live in "
                "`../concepts/MODEL.md`; this notebook is the intuitive version.",
            )
        ),
        md(
            "## Learning objectives\n"
            "\n"
            "- Understand astronomical tidal forcing and the M2/S2/K1/O1 "
            "constituents.\n"
            "- Appreciate the spring–neap cycle and why runs last ≥ 15 days.\n"
            "- See why power density scales as ½ρU³.\n"
            "- Explain how a tidal-stream turbine converts the current into "
            "power.\n"
            "- Understand the funnel effect and the screening cascade.\n"
        ),
        md(
            "## 1.1 Tides are a sum of harmonics\n"
            "\n"
            "The ocean is not forced by one single wave. Tides are long-period "
            "surface gravity waves generated by the gravitational pull of the "
            "Moon and the Sun as the Earth rotates beneath them. The dominant "
            "component is the **semi-diurnal lunar tide (M2)** at 12.42 hours — "
            "the time between successive passes of the Moon over a given "
            "meridian. Because the tidal wave is forced at ocean-basin scale it "
            "propagates as a shallow-water wave: even in the deepest ocean "
            "(~5 km) the wavelength vastly exceeds the depth, so the whole "
            "water column moves in phase.\n"
            "\n"
            "Real tides are a **superposition** of such harmonics, each with an "
            "amplitude and a phase locked to an astronomical period. At any "
            "point the free surface is the sum:\n"
            "\n"
            "$$\\eta(t) = \\sum_k A_k \\cos(\\omega_k t + \\phi_k)$$\n"
            "\n"
            "where $A_k$ is the amplitude in metres, $\\omega_k = 2\\pi/T_k$ the "
            "angular frequency, and $\\phi_k$ the phase. The four constituents "
            "below account for ~80–90% of tidal variability in most of the "
            "world ocean, which is why the project forces the model with them "
            "by default:\n"
            "\n"
            "| Constituent | Origin | Period | Typical amplitude (PH) |\n"
            "|-------------|--------|--------|-------------------------|\n"
            "| M2 | Principal lunar semi-diurnal | 12.42 h | 0.3–1.0 m |\n"
            "| S2 | Principal solar semi-diurnal | 12.00 h | 0.1–0.3 m |\n"
            "| K1 | Luni-solar diurnal | 23.93 h | 0.2–0.5 m |\n"
            "| O1 | Principal lunar diurnal | 25.82 h | 0.1–0.3 m |\n"
            "\n"
            "The cell below reconstructs $\\eta(t)$ from all four constituents "
            "and plots the total alongside each individual harmonic. Notice "
            "how the slow diurnal constituents (K1, O1) act as a slowly varying "
            "baseline underneath the fast semi-diurnals (M2, S2) — this is the "
            "same summation the model performs at every open-boundary cell.\n"
        ),
        code(
            "%matplotlib inline\n"
            "import numpy as np\n"
            "import matplotlib.pyplot as plt\n"
            "\n"
            "t_h = np.linspace(0.0, 48.0, 2000)   # two days, in hours\n"
            "\n"
            "constituents = [\n"
            "    ('M2', 0.50, 12.4206012),   # principal lunar semi-diurnal\n"
            "    ('S2', 0.20, 12.0),         # principal solar semi-diurnal\n"
            "    ('K1', 0.25, 23.9344696),   # luni-solar diurnal\n"
            "    ('O1', 0.15, 25.8193417),   # principal lunar diurnal\n"
            "]\n"
            "\n"
            "eta = np.zeros_like(t_h)\n"
            "for name, amp, period in constituents:\n"
            "    eta += amp * np.cos(2 * np.pi * t_h / period)\n"
            "    print(f'{name}: A = {amp:.2f} m, T = {period:.4f} h')\n"
            "\n"
            "fig, ax = plt.subplots(figsize=(10, 3.5))\n"
            "ax.plot(t_h / 24.0, eta, lw=1.1, label='sum of the 4 constituents')\n"
            "for name, amp, period in constituents:\n"
            "    ax.plot(t_h / 24.0, amp * np.cos(2 * np.pi * t_h / period),\n"
            "            lw=0.5, alpha=0.4)\n"
            "ax.set_xlabel('days')\n"
            "ax.set_ylabel('η (m)')\n"
            "ax.set_title('M2 + S2 + K1 + O1 — two days of elevation')\n"
            "ax.legend(loc='upper right', fontsize=8)\n"
            "plt.tight_layout()\n"
            "plt.show()\n"
        ),
        img(
            "fig_tidal_superposition.png",
            "Superposition of M2, S2, K1 and O1 over two days.",
        ),
        md(
            "## 1.2 Power density: the ½ρU³ law\n"
            "\n"
            "A tidal-stream turbine converts **kinetic** energy. The quantity "
            "that matters is the instantaneous power per unit swept area — the "
            "kinetic-energy flux through the rotor disk:\n"
            "\n"
            "$$P = \\tfrac{1}{2} \\rho U^3 \\qquad [\\text{W/m}^2]$$\n"
            "\n"
            "with $\\rho = 1025$ kg/m³ (seawater) and $U = \\sqrt{u^2+v^2}$ the "
            "depth-averaged current speed. The cube follows from three simple "
            "factors:\n"
            "\n"
            "1. Kinetic energy per unit volume: $\\tfrac{1}{2}\\rho U^2$.\n"
            "2. Volume flux per unit area per unit time: $U$ (m³/s per m²).\n"
            "3. Product: $\\tfrac{1}{2}\\rho U^2 \\times U = \\tfrac{1}{2}\\rho U^3$.\n"
            "\n"
            "The cubic dependence is the defining feature of tidal-stream "
            "resource assessment: **doubling the speed gives eight times the "
            "power**. A site at 2.5 m/s is not 25% better than one at 2.0 m/s — "
            "it yields almost double the power density. This is why accurate "
            "velocity prediction matters so much for site selection. Run the "
            "two cells below: the first tabulates the law, the second plots it "
            "and highlights the 1 → 2 m/s jump.\n"
        ),
        code(
            "RHO = 1025.0   # kg/m^3 seawater\n"
            "print(' U [m/s]    P [W/m^2]')\n"
            "for u in (0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0):\n"
            "    print(f'  {u:4.1f}    {0.5 * RHO * u**3:9.1f}')\n"
        ),
        code(
            "import numpy as np\n"
            "import matplotlib.pyplot as plt\n"
            "\n"
            "RHO = 1025.0   # kg/m^3 seawater\n"
            "u = np.linspace(0.0, 4.0, 200)\n"
            "p = 0.5 * RHO * u**3\n"
            "\n"
            "fig, ax = plt.subplots(figsize=(7, 4))\n"
            "ax.plot(u, p, lw=2)\n"
            "for uu in (1.0, 2.0):\n"
            "    ax.axvline(uu, ls=':', color='grey')\n"
            "ax.annotate('U = 2.0 m/s gives 8× the power of U = 1.0 m/s',\n"
            "            xy=(2.0, 0.5 * RHO * 8.0), xytext=(1.3, 14000),\n"
            "            arrowprops=dict(arrowstyle='->'), fontsize=8)\n"
            "ax.set_xlabel('depth-averaged current speed U (m/s)')\n"
            "ax.set_ylabel('power density P (W/m^2)')\n"
            "ax.set_title('½ρU³ — why small speed gains are huge power gains')\n"
            "plt.tight_layout()\n"
            "plt.show()\n"
        ),
        img(
            "fig_cubic_power.png",
            "Power density grows with the cube of current speed (½ρU³).",
        ),
        md(
            "## 1.3 How tidal-stream turbines work\n"
            "\n"
            "So far we have built up the resource: the free surface, the "
            "current it drives, and the kinetic-energy flux ½ρU³ that travels "
            "with it. The machine that harvests that flux is a **tidal "
            "in-stream turbine** — the underwater cousin of a wind turbine. A "
            "rotor of blades spins as the current pushes past them, the hub "
            "turns a generator, and electricity is cabled to shore.\n"
            "\n"
            "**The energy chain.** The current does work on the rotor. The "
            "rotor converts the kinetic energy of the moving water into "
            "rotational mechanical energy, the shaft spins a generator "
            "(often through a gearbox, sometimes direct-drive), and the "
            "generator produces AC electricity that a subsea cable carries to "
            "the grid. The whole chain is driven by a single input: the speed "
            "of the water through the swept area.\n"
            "\n"
            "**Swept area.** A rotor of diameter $D$ sweeps "
            "$A = \\pi D^2/4$. The kinetic energy arriving at the rotor per "
            "second is the flux through that area:\n"
            "\n"
            "$$P_{\\text{available}} = \\tfrac{1}{2}\\rho A U^3$$\n"
            "\n"
            "**The Betz limit.** A rotor cannot stop the water — the flow must "
            "keep moving, so only a fraction of the incoming kinetic energy "
            "can be captured. Momentum theory (the same argument that limits "
            "wind turbines) caps that fraction at $16/27 \\approx 59.3\\%$, the "
            "**Betz limit**. Real turbines reach a power coefficient "
            "$C_p \\approx 0.35\\text{–}0.45$, so the practical output is:\n"
            "\n"
            "$$P = \\tfrac{1}{2}\\rho A U^3 \\, C_p$$\n"
            "\n"
            "Everything that made $U^3$ special for the resource is doubled "
            "down here: a turbine at a 2.5 m/s site extracts roughly eight "
            "times the power of one at a 1.25 m/s site. Turbines are tuned to "
            "the *range* of speeds at a specific strait.\n"
            "\n"
            "**The power curve.** A turbine operates in three regimes:\n"
            "\n"
            "| Regime | Condition | Behaviour |\n"
            "|--------|-----------|-----------|\n"
            "| Below cut-in | $U < U_{\\text{cut-in}}$ | No power; the current is too weak to turn the rotor usefully |\n"
            "| Cubic ramp | $U_{\\text{cut-in}} \\le U < U_{\\text{rated}}$ | Output grows as $U^3$ |\n"
            "| Rated plateau | $U_{\\text{rated}} \\le U < U_{\\text{cut-out}}$ | Output held at rated power (blade pitch / stall control) |\n"
            "| Cut-out | $U \\ge U_{\\text{cut-out}}$ | Turbine brakes to protect the machine |\n"
            "\n"
            "Typical tidal devices have cut-in ~0.5–1 m/s, rated speed "
            "~1.8–2.5 m/s, and cut-out ~3–4 m/s.\n"
            "\n"
            "**Two-way currents.** Unlike wind, the tide reverses — flood then "
            "ebb, twice a day. Rotors therefore either pitch their blades to "
            "face the flow or are symmetric and work in both directions; some "
            "designs yaw the whole nacelle. The reversal also means a turbine "
            "is idle for part of every tidal cycle, which is why the *mean* "
            "output over a spring–neap cycle — not the peak — determines the "
            "**capacity factor** (mean output ÷ rated power). Tidal sites "
            "typically deliver capacity factors of ~20–40%.\n"
            "\n"
            "The two cells below put numbers on this: the first computes the "
            "available flux, the Betz limit, and the output of a "
            "representative rotor; the second plots its full power curve. The "
            "project's web layer (Notebook 5) ships a curated set of real "
            "turbines with exactly this kind of power-curve model.\n"
        ),
        code(
            "import numpy as np\n"
            "\n"
            "rho = 1025.0\n"
            "D = 20.0                      # rotor diameter (m)\n"
            "A = np.pi * (D / 2) ** 2      # swept area (m^2)\n"
            "Cp = 0.40                     # power coefficient (Betz = 16/27 ≈ 0.593)\n"
            "\n"
            "U_rated = 2.4                 # speed at rated power (m/s)\n"
            "P_rated = 0.5 * rho * A * U_rated ** 3 * Cp\n"
            "\n"
            "print(f'swept area A          : {A:7.1f} m^2')\n"
            "print(f'available flux @2.0   : {0.5 * rho * A * 2.0**3 / 1e3:7.1f} kW')\n"
            "print(f'Betz limit 16/27      : {16 / 27:7.3f}')\n"
            "print(f'output @2.0 (Cp=0.40) : {0.5 * rho * A * 2.0**3 * Cp / 1e3:7.1f} kW')\n"
            "print(f'rated power @{U_rated:.1f}   : {P_rated / 1e3:7.1f} kW')\n"
        ),
        code(
            "import numpy as np\n"
            "import matplotlib.pyplot as plt\n"
            "\n"
            "rho, D, Cp = 1025.0, 20.0, 0.40\n"
            "A = np.pi * (D / 2) ** 2\n"
            "U_cut_in, U_rated, U_cut_out = 0.7, 2.4, 4.0\n"
            "P_rated = 0.5 * rho * A * U_rated ** 3 * Cp\n"
            "\n"
            "u = np.linspace(0.0, U_cut_out + 0.5, 300)\n"
            "p = np.where(u < U_cut_in, 0.0,\n"
            "             np.where(u < U_rated, 0.5 * rho * A * u**3 * Cp, P_rated))\n"
            "\n"
            "fig, ax = plt.subplots(figsize=(7, 4))\n"
            "ax.plot(u, p / 1e3, lw=2)\n"
            "ymax = p.max() / 1e3\n"
            "for x, lab in [(U_cut_in, 'cut-in'), (U_rated, 'rated'),\n"
            "               (U_cut_out, 'cut-out')]:\n"
            "    ax.axvline(x, ls=':', color='grey')\n"
            "    ax.text(x, 0.06 * ymax, lab, ha='center', fontsize=8)\n"
            "ax.set_xlabel('current speed U (m/s)')\n"
            "ax.set_ylabel('output power (kW)')\n"
            "ax.set_title(f'Power curve of a {D:.0f} m rotor (Cp = {Cp:.2f}, '\n"
            "              f'rated = {P_rated / 1e3:.0f} kW)')\n"
            "plt.tight_layout()\n"
            "plt.show()\n"
        ),
        img(
            "fig_turbine_power_curve.png",
            "Power curve of a 20 m rotor with cut-in, rated and cut-out.",
        ),
        md(
            "## 1.4 Spring–neap modulation\n"
            "\n"
            "M2 and S2 have nearly the same period — 12.42 h versus 12.00 h — "
            "so their sum produces a **beat**: an envelope whose amplitude "
            "grows and decays as the two components drift in and out of phase. "
            "When they are in phase the range is maximum (**spring tide**, big "
            "currents); when they are half a period apart the range is minimum "
            "(**neap tide**, weak currents).\n"
            "\n"
            "The beat period is the inverse of the frequency difference:\n"
            "\n"
            "$$T_{\\text{beat}} = \\frac{1}{1/T_{S2} - 1/T_{M2}} \\approx 354\\text{ h} \\approx 14.77\\text{ days}$$\n"
            "\n"
            "This is why the simulation runs for **at least 15 days**. A shorter "
            "run risks sampling only springs (over-estimating the resource) or "
            "only neaps (under-estimating it). The cells below compute the beat "
            "period and plot the full 30-day envelope so you can see the "
            "springs and neaps by eye.\n"
        ),
        code(
            "import numpy as np\n"
            "\n"
            "T_M2, T_S2 = 12.4206012, 12.0   # hours\n"
            "T_beat = 1.0 / (1.0 / T_S2 - 1.0 / T_M2)\n"
            "print(f'beat period: {T_beat:6.1f} h = {T_beat / 24.0:5.2f} days')\n"
            "print(f'a 15-day run covers {15.0 / (T_beat / 24.0):.1f} beat(s)')\n"
        ),
        code(
            "import numpy as np\n"
            "import matplotlib.pyplot as plt\n"
            "\n"
            "t_h = np.linspace(0.0, 30.0 * 24.0, 6000)          # 30 days in hours\n"
            "eta = (0.5 * np.cos(2 * np.pi * t_h / 12.4206012)\n"
            "       + 0.2 * np.cos(2 * np.pi * t_h / 12.0))    # M2 + S2\n"
            "\n"
            "fig, ax = plt.subplots(figsize=(10, 3.5))\n"
            "ax.plot(t_h / 24.0, eta, lw=0.8)\n"
            "ax.set_xlabel('days')\n"
            "ax.set_ylabel('η (m)')\n"
            "ax.set_title('M2 + S2 elevation — the spring–neap envelope (14.77 d beat)')\n"
            "plt.tight_layout()\n"
            "plt.show()\n"
        ),
        img(
            "fig_spring_neap.png",
            "The M2 + S2 beat produces a 14.77-day spring–neap envelope.",
        ),
        md(
            "## 1.5 From elevation to current\n"
            "\n"
            "A tide gauge measures water level, but a turbine extracts kinetic "
            "energy from the **current**. How does a one-metre surface slope "
            "become a multi-metre-per-second flow? That is the job of the "
            "depth-averaged shallow-water equations.\n"
            "\n"
            "**Continuity** conserves volume: if water converges into a cell "
            "the surface rises:\n"
            "\n"
            "$$\n"
            "\\frac{\\partial \\eta}{\\partial t}\n"
            "+ \\frac{\\partial}{\\partial x}(h u)\n"
            "+ \\frac{\\partial}{\\partial y}(h v) = 0\n"
            "$$\n"
            "\n"
            "**Momentum** is Newton's second law: a surface slope is a pressure "
            "gradient that accelerates water downhill, balanced by friction and "
            "Coriolis:\n"
            "\n"
            "$$\n"
            "\\frac{\\partial u}{\\partial t}\n"
            "= -g\\,\\frac{\\partial \\eta}{\\partial x}\n"
            " + f v - \\frac{C_d}{h}\\,|u|\\,u\n"
            "$$\n"
            "\n"
            "| Term | Physics | When it matters |\n"
            "|------|---------|-----------------|\n"
            "| Pressure gradient $-g\\,\\partial\\eta/\\partial x$ | Water accelerates from high η to low η — the primary driver | Always |\n"
            "| Coriolis $f v$ | Earth's rotation deflects flow to the right (N hemisphere) | Scales > 10 km |\n"
            "| Bottom friction $C_d\\,|u|\\,u/h$ | Seabed shear stress, the main energy sink | Dominant in shallow channels |\n"
            "\n"
            "Bottom friction is inversely proportional to depth ($1/h$): in deep "
            "water the tide propagates almost as a free wave, while in a shallow "
            "channel friction dominates and caps the current. That is why "
            "shallow channels are lossy and why depth is such a strong predictor "
            "of current speed.\n"
            "\n"
            "The code cell below integrates the momentum balance for a single "
            "channel (no Coriolis, no advection) forced by a sinusoidal "
            "along-channel slope. After a spin-up of a few M2 periods the "
            "current settles into a periodic response whose amplitude matches "
            "the prediction of Lorentz linearisation, "
            "$|u|u \\approx (8/3\\pi)\\,U\\,u$ — a concrete check that the "
            "equation really does turn elevation into current.\n"
        ),
        code(
            "import numpy as np\n"
            "\n"
            "g, h, cd, S0 = 9.81, 50.0, 0.0025, 1e-5\n"
            "T = 12.4206012 * 3600.0          # M2 period in seconds\n"
            "omega = 2 * np.pi / T\n"
            "\n"
            "# Lorentz linearisation: |u|u ≈ (8/3π) U u  ⇒  solve\n"
            "#   (ωU)^2 + [(8/3π)·(cd/h)·U^2]^2 = (g·S0)^2  for U\n"
            "def residual(U):\n"
            "    return ((omega * U) ** 2\n"
            "            + ((8 / (3 * np.pi)) * (cd / h) * U ** 2) ** 2\n"
            "            - (g * S0) ** 2)\n"
            "\n"
            "lo, hi = 0.0, 10.0\n"
            "for _ in range(100):\n"
            "    mid = 0.5 * (lo + hi)\n"
            "    if residual(mid) > 0:\n"
            "        hi = mid\n"
            "    else:\n"
            "        lo = mid\n"
            "U_lorentz = 0.5 * (lo + hi)\n"
            "\n"
            "# numeric integration of  du/dt = -g·S0·cos(ωt) - (cd/h)·|u|·u\n"
            "dt, dur = 5.0, 15.0 * T\n"
            "t = np.arange(0.0, dur, dt)\n"
            "u = 0.0\n"
            "U = np.empty(t.size)\n"
            "for i, ti in enumerate(t):\n"
            "    u += dt * (-g * S0 * np.cos(omega * ti) - (cd / h) * abs(u) * u)\n"
            "    U[i] = u\n"
            "\n"
            "U_num = np.max(np.abs(U[int(0.7 * t.size):]))\n"
            "print(f'Lorentz estimate : {U_lorentz:.3f} m/s')\n"
            "print(f'numeric amplitude: {U_num:.3f} m/s')\n"
            "print(f'ratio            : {U_num / U_lorentz:.2f}')\n"
        ),
        md(
            "## 1.6 The funnel effect and hotspots\n"
            "\n"
            "Mass conservation $Q = A\\,U$ (volume flux = cross-sectional area "
            "× speed) has a striking consequence. If a channel narrows from "
            "width $W_1$ to $W_2$ and shallows from $h_1$ to $h_2$, the same "
            "flux must squeeze through a smaller area, so the current "
            "accelerates:\n"
            "\n"
            "$$U_2 \\approx U_1 \\, \\frac{W_1}{W_2}\\, \\frac{h_1}{h_2}$$\n"
            "\n"
            "This is the **funnel effect** — why straits are hotspots. The "
            "Philippine archipelago is exceptionally rich in these constriction "
            "sites because it sits at the junction of several tidal basins with "
            "different phases: the Pacific (large M2 amplitude), the South "
            "China Sea (smaller, different phase), the Sulu Sea (resonant, "
            "semi-enclosed), and the Celebes Sea. The phase differences between "
            "basins drive strong flows through the inter-island straits:\n"
            "\n"
            "| Strait | Peak spring current | Power density (est.) |\n"
            "|--------|---------------------|----------------------|\n"
            "| San Bernardino Strait | 3–4 m/s | > 1000 W/m² |\n"
            "| Surigao Strait | 2–3 m/s | 500–1000 W/m² |\n"
            "| Basilan Strait | 2–2.5 m/s | 200–500 W/m² |\n"
            "| Verde Island Passage | 1.5–2 m/s | 100–300 W/m² |\n"
            "\n"
            "The code cell below runs an idealised funnel: it fixes the volume "
            "flux and shows how speed — and hence power density — jump as the "
            "channel narrows. The real model is more complex (friction and "
            "unsteadiness cap the acceleration), but this is the first-order "
            "mechanism that makes straits worth investigating.\n"
        ),
        code(
            "# Idealised, frictionless funnel: Q = A·U is conserved\n"
            "Q = 1.0e6                    # volume flux, m^3/s (illustrative)\n"
            "W1, h1 = 10000.0, 50.0      # wide/deep channel: 10 km × 50 m\n"
            "W2, h2 = 5000.0, 40.0       # narrow/shallow:   5 km × 40 m\n"
            "\n"
            "U1 = Q / (W1 * h1)\n"
            "U2 = Q / (W2 * h2)\n"
            "print(f'wide channel   : U1 = {U1:5.2f} m/s')\n"
            "print(f'narrow channel : U2 = {U2:5.2f} m/s')\n"
            "print(f'speed-up       : {U2 / U1:4.1f}×')\n"
            "print(f'power ratio    : {(U2 / U1) ** 3:5.1f}×   (power ∝ U³)')\n"
        ),
        img(
            "fig_funnel_effect.png",
            "The funnel effect: Q = A·U means a narrowing channel accelerates the current.",
        ),
        md(
            "## 1.7 The screening cascade\n"
            "\n"
            "The project deliberately does **not** try to resolve every strait "
            "at high resolution from day one. It uses a screening cascade that "
            "fails fast and fails cheap — each tier is more expensive, so only "
            "the sites that survive the previous tier move on:\n"
            "\n"
            "```\n"
            "Coarse Python model (this project's Phase A)\n"
            "        │\n"
            "        ▼\n"
            "   Sites with P_mean > 200 W/m²  (hotspots.geojson)\n"
            "        │\n"
            "        ▼\n"
            "   High-resolution TELEMAC-2D unstructured mesh (Phase B)\n"
            "        │\n"
            "        ▼\n"
            "   Turbine-array CFD / actuator-disk modelling\n"
            "        │\n"
            "        ▼\n"
            "   Geophysical / environmental surveys\n"
            "        │\n"
            "        ▼\n"
            "   Pilot deployment\n"
            "```\n"
            "\n"
            "The screening model is **deliberately conservative**: coarse "
            "resolution and depth-averaging both *under-estimate* peak currents, "
            "so any site it flags as promising is almost certainly worth a "
            "closer look with the finer tools. The 200 W/m² threshold is the "
            "gateway between the first two tiers.\n"
        ),
        img(
            "fig_screening_cascade.png",
            "The screening cascade: cheap coarse tiers first, expensive refinement only for survivors.",
        ),
        md(
            "## Next\n"
            "\n"
            "Concepts are covered; move to "
            "[Notebook 2 — data](2.data.ipynb) to see what the project ingests "
            "and publishes." + nav(prev="0.setup.ipynb", nxt="2.data.ipynb"),
        ),
    ]


# ---------------------------------------------------------------------------
# 2. data
# ---------------------------------------------------------------------------
# 2. data
# ---------------------------------------------------------------------------
def n_data() -> list[dict]:
    return [
        md(
            header(
                "Notebook 2",
                "Data: inputs, configuration, and outputs",
                "This notebook walks through the data the project consumes and "
                "produces, then reads each canonical output from disk. It also "
                "tours the online portals and repositories where the external "
                "datasets can be downloaded, with screenshots of each. These are "
                "the files the web application serves.",
            )
        ),
        md(
            "## Learning objectives\n"
            "\n"
            "- Map the external inputs to `src/model/config.yaml`.\n"
            "- Tour the online data portals and repositories behind each "
            "input (bathymetry, land mask, tidal forcing).\n"
            "- Name the six canonical output files and where they live.\n"
            "- Read the power raster, the NetCDF time series, and the hotspot "
            "GeoJSON.\n"
        ),
        md(
            "## 2.1 Inputs\n"
            "\n"
            "The screening model needs three kinds of external input, all "
            "declared in `src/model/config.yaml`:\n"
            "\n"
            "| Input | Source | Role |\n"
            "|-------|--------|------|\n"
            "| Bathymetry | **GEBCO 2026** NetCDF | Seabed depth *h* (m, positive down) |\n"
            "| Tidal harmonics | **GOT4.10c** / FES2014 / TPXO9 (or synthetic) | M2/S2/K1/O1 amplitudes & phases |\n"
            "| Land mask | **Philippines landmass GeoJSON** (GeoBoundaries ADM0) | Mark dry cells |\n"
            "\n"
            "The next section visits the websites that publish these datasets. "
            "Every one of them is free to download (some require a one-time "
            "registration). `downloader.py` automates the ones with direct "
            "URLs; the rest are documented so you can fetch them by hand.\n"
        ),
        code(
            "try:\n"
            "    from model.config import load_config\n"
            "    cfg = load_config()\n"
            "    print('domain        :', cfg['domain'])\n"
            "    print('bathymetry    :', cfg['bathymetry'].get('path'))\n"
            "    print('land mask     :', cfg['bathymetry'].get('land_shapefile'))\n"
            "    print('forcing source:', cfg['tidal_forcing'].get('source'))\n"
            "    print('constituents  :', cfg['tidal_forcing'].get('constituents'))\n"
            "    print('duration_days :', cfg['simulation'].get('duration_days'))\n"
            "    print('resolution_km :', cfg['domain'].get('resolution_km'))\n"
            "    print('hotspot thr.  :', cfg['output'].get('hotspot_threshold'), 'W/m^2')\n"
            "    print('engine        :', cfg['engine'].get('name'))\n"
            "except Exception as exc:\n"
            "    print('config not loaded:', exc)\n"
        ),
        md(
            "## 2.2 The online data landscape\n"
            "\n"
            "Tidal-energy resource assessment is data-hungry. You need a "
            "terrain model for the seabed, a coastline to separate water from "
            "land, and a tidal model to know how high and how fast the water "
            "moves. This section surveys the leading free repositories for "
            "each, in the same order the model consumes them. Screenshots were "
            "captured with Playwright; the capture script lives at "
            "`scripts/capture_portal_screenshots.py`.\n"
            "\n"
            "### 2.2.1 Bathymetry — GEBCO and friends\n"
            "\n"
            "#### GEBCO — the global grid\n"
            "\n"
            "GEBCO (General Bathymetric Chart of the Oceans) is an "
            "international programme that assembles the global GEBCO Grid — a "
            "continuous **15 arc-second (~450 m)** terrain model covering both "
            "oceans and land, published annually (GEBCO 2024, 2025, 2026, ...). "
            "It is the standard, freely available bathymetry used in marine "
            "energy screening studies worldwide. The grid is distributed as a "
            "global NetCDF (~7 GB), as eight 90°×90° GeoTIFF tiles, and in "
            "Esri ASCII; the site also documents the licence terms and the "
            "recommended citation (doi:10.5285/4f68d5c7-45eb-f999-e063-7086abc036fa).\n"
            "\n"
            "In this project: `data/gebco/gebco_2026_n22.0_s4.0_w112.0_e128.0.nc` "
            "is a Philippine-region subset of the GEBCO 2026 grid, read by "
            "`bathymetry.load_gebco`.\n"
            "\n"
            "![GEBCO gridded bathymetry data page](images/portal-gebco.png)\n"
        ),
        md(
            "#### GEBCO Download App (subsetting)\n"
            "\n"
            "Because the full global grid is huge, GEBCO provides an "
            "interactive **Download App** where you draw a bounding box on a "
            "map and download only that region in NetCDF, GeoTIFF, or Esri "
            "ASCII. You can add several regions to a basket and receive a zip "
            "of processed subsets. This is the fastest way to grab a modest "
            "area like the Philippines by hand.\n"
            "\n"
            "In this project: the old app's output filename scheme "
            "(`gebco_2026_n<latmax>_s<latmin>_w<lonmin>_e<lonmax>.nc`) is kept "
            "verbatim by `downloader.py` so files produced here and by the "
            "script are interchangeable.\n"
            "\n"
            "![GEBCO subsetting app](images/portal-gebco-subset.png)\n"
        ),
        md(
            "#### GEBCO on CEDA — the official archive\n"
            "\n"
            "The authoritative direct-download home of the GEBCO grids is the "
            "Centre for Environmental Data Analysis (**CEDA**), part of the UK "
            "Natural Environment Research Council. It archives the global "
            "NetCDF, the GeoTIFF tiles, the Type-Identifier (TID) grid, and "
            "offers OPeNDAP access for programmatic subsetting. The global "
            "ice-surface NetCDF is ~7 GB — fine for a one-off download, but "
            "overkill when you only need one archipelago.\n"
            "\n"
            "In this project: the COG mirror in §2.2.1 (below) reads the same "
            "underlying grid, so you normally do not need to visit CEDA.\n"
            "\n"
            "![GEBCO 2026 on CEDA](images/portal-gebco-ceda.png)\n"
        ),
        md(
            "#### GEBCO as a Cloud-Optimized GeoTIFF (source.coop)\n"
            "\n"
            "data.source.coop is a community-run data cooperative that "
            "re-publishes popular geospatial datasets as **Cloud-Optimized "
            "GeoTIFFs (COGs)** for fast, range-based access. This mirror of "
            "GEBCO 2026 (`giswqs/gebco-bathymetry`) lets a client fetch only "
            "the tiles it needs over plain HTTP — no 7 GB download. The COG "
            "carries the original 15 arc-second values plus internal overviews "
            "for fast zooming.\n"
            "\n"
            "In this project: `downloader.py --gebco` opens this COG with "
            "`rasterio` and reads just the Philippines window (~17 MB) before "
            "writing the GEBCO-format NetCDF. This is the automated path you "
            "will actually use.\n"
            "\n"
            "![GEBCO COG mirror on source.coop](images/portal-gebco-cog.png)\n"
        ),
        md(
            "#### EMODnet Bathymetry (regional complement)\n"
            "\n"
            "EMODnet Bathymetry is a European Commission portal that "
            "harmonizes thousands of national surveys into a high-resolution "
            "Digital Terrain Model for European waters, filling gaps with "
            "GEBCO. It provides a DTM viewer, WMS/WFS services, and free "
            "downloads. It is a good example of a survey-graded regional "
            "product you might swap in for the global grid in a European study.\n"
            "\n"
            "In this project: not used (Philippine domain), but a useful "
            "reference for how regional surveys upgrade global grids.\n"
            "\n"
            "![EMODnet Bathymetry portal](images/portal-emodnet.png)\n"
        ),
        md(
            "### 2.2.2 Land boundaries — where the coast is\n"
            "\n"
            "#### GeoBoundaries\n"
            "\n"
            "geoBoundaries is a free, open-source repository of administrative "
            "boundaries (ADM0–ADM5) for every country, maintained by the "
            "GeoLab at William & Mary. It exposes a REST API "
            "(`api.geoboundaries.org`) that returns download links for "
            "GeoJSON, Shapefile, and TopoJSON, and is updated from official "
            "sources. It is lightweight, licence-permissive, and perfect for "
            "grabbing a country outline as a land mask.\n"
            "\n"
            "In this project: `data/philippines_landmass.geojson` is the "
            "Philippines ADM0 outline from geoBoundaries, downloaded by "
            "`downloader.py --landmask` and rasterised by "
            "`bathymetry.build_land_mask`.\n"
            "\n"
            "![GeoBoundaries](images/portal-geoboundaries.png)\n"
        ),
        md(
            "#### GADM\n"
            "\n"
            "GADM is a widely used, high-resolution database of country "
            "administrative areas, with polygon and line layers from country "
            "level down to level 5. Each country can be downloaded free as a "
            "shapefile or GeoPackage, and the dataset is a common source of "
            "`ADM0` country polygons in GIS workflows. It is a solid "
            "alternative to GeoBoundaries for building the Philippine land "
            "mask.\n"
            "\n"
            "In this project: an alternative land-mask source — the country "
            "outline layer (`gadm41_PHL_0`) is equivalent to the GeoBoundaries "
            "ADM0 used by default.\n"
            "\n"
            "![GADM](images/portal-gadm.png)\n"
        ),
        md(
            "#### OpenStreetMap via Geofabrik\n"
            "\n"
            "Geofabrik is a company that publishes free, regularly updated "
            "extracts of OpenStreetMap for continents, countries, and "
            "regions. Its country pages offer raw OSM data as well as a "
            "'free' shapefile bundle — including water polygons, coastlines, "
            "and land polygons — ready for GIS use. The coastline/land-polygon "
            "layers are a well-known way to derive a fine-scale land mask.\n"
            "\n"
            "In this project: an alternative coastline source for the land "
            "mask, often at higher spatial fidelity than ADM0 outlines.\n"
            "\n"
            "![Geofabrik Philippines page](images/portal-geofabrik.png)\n"
        ),
        md(
            "### 2.2.3 Tidal forcing — global ocean tide models\n"
            "\n"
            "#### NASA GSFC — GOT4.10c (Goddard Ocean Tide)\n"
            "\n"
            "NASA Goddard's Geodesy and Geophysics Laboratory publishes the "
            "**GOT** family of global ocean tide models, derived from decades "
            "of satellite altimetry (Topex/Poseidon, Jason, ...). GOT4.10c is "
            "a freely downloadable, **no-registration** archive of "
            "per-constituent grids (M2, S2, K1, O1, ...) in ASCII and NetCDF, "
            "on a 0.5° grid. It is the recommended tidal forcing for this "
            "workshop because it is both free and simple to automate.\n"
            "\n"
            "In this project: the default forcing — "
            "`data/GOT4.10c/grids_oceantide_netcdf/*.nc` is read by "
            "`forcing.read_got_constituents`.\n"
            "\n"
            "![NASA GSFC ocean tide models](images/portal-nasa-got.png)\n"
        ),
        md(
            "#### AVISO — FES2014\n"
            "\n"
            "FES2014 (Finite Element Solution) is a global tide model "
            "developed by NOVELTIS/LEGOS/CLS and distributed by **AVISO**, the "
            "altimetry data centre. It provides amplitude and phase for about "
            "34 constituents on a 1/16° grid, the finest of the three models "
            "covered here. Access requires a free AVISO registration, so the "
            "downloader can only document it, not automate it.\n"
            "\n"
            "In this project: an alternative forcing — per-constituent files "
            "(`M2_ocean.nc`, `M2_load.nc`, ...) would be placed in "
            "`data/fes2014/` and selected with "
            "`tidal_forcing.source: fes2014`.\n"
            "\n"
            "![AVISO FES2014](images/portal-aviso-fes.png)\n"
        ),
        md(
            "#### Oregon State University — TPXO9-atlas\n"
            "\n"
            "TPXO is Oregon State University's series of global barotropic "
            "ocean tide models; **TPXO9-atlas** is the latest high-resolution "
            "release (~1/30°) with around 90 tidal constituents in one "
            "NetCDF. The portal hosts the grids and an interactive viewer; "
            "downloads require a simple registration. It is the "
            "highest-resolution tide model the project's forcing reader "
            "supports.\n"
            "\n"
            "In this project: an alternative forcing — the single grid file "
            "(`h_tpxo9.v1.nc`) would be placed in `data/tpxo9/` and selected "
            "with `tidal_forcing.source: tpxo9`.\n"
            "\n"
            "![TPXO9-atlas](images/portal-tpxo.png)\n"
        ),
        md(
            "#### pyTMD — programmatic access to all of the above\n"
            "\n"
            "pyTMD is an open-source Python library (NASA/JPL, Tyler "
            "Sutterley) that downloads, reads, and evaluates ocean tide models "
            "including GOT, FES, TPXO, and more. Its `fetch_gsfc_got()` "
            "function can automate the GOT4.10c archive download used here, "
            "and its readers understand the same per-constituent NetCDF "
            "format. It is a handy reference implementation if you ever need "
            "constituents outside the M2/S2/K1/O1 set.\n"
            "\n"
            "In this project: not required, but a useful cross-check for the "
            "harmonic values the model interpolates.\n"
            "\n"
            "![pyTMD documentation](images/portal-pytmd.png)\n"
        ),
        md(
            "### 2.2.4 The downloader manifest\n"
            "\n"
            "All of this is wired into `downloader.py`, which mirrors exactly "
            "the files `config.yaml` expects. The cell below prints the "
            "live URL manifest so you can see the mapping from repository to "
            "download command at a glance.\n"
        ),
        code(
            "import sys\n"
            "from pathlib import Path\n"
            "\n"
            "root = next((c for c in (Path('.'), Path('../..'))\n"
            "             if (c / 'downloader.py').exists()), Path('.'))\n"
            "sys.path.insert(0, str(root))\n"
            "\n"
            "try:\n"
            "    import downloader as dl\n"
            "    for key, ds in dl.DATASETS.items():\n"
            "        urls = list(ds.get('urls') or [])\n"
            "        if ds.get('fetcher') == 'gebco_subset':\n"
            "            urls.append(dl.GEBCO_COG_URL)\n"
            "        print(f'{key:12s}  {ds[\"name\"]}')\n"
            "        for u in urls:\n"
            "            print(f'          {u}')\n"
            "except Exception as exc:\n"
            "    print('downloader module not importable:', exc)\n"
        ),
        md(
            "| Input | Repository / portal | Config key | Download |\n"
            "|-------|---------------------|------------|----------|\n"
            "| Bathymetry | GEBCO 2026 — gebco.net · CEDA · source.coop COG | `bathymetry.path` | `--gebco` |\n"
            "| Land mask | GeoBoundaries ADM0 · GADM · OSM/Geofabrik | `bathymetry.land_shapefile` | `--landmask` |\n"
            "| Tidal forcing | NASA GOT4.10c · AVISO FES2014 · TPXO9 | `tidal_forcing.path` | `--tidal` |\n"
            "\n"
            "Run `python downloader.py --all` to fetch the three automated "
            "datasets; FES2014 and TPXO9 print manual instructions because "
            "they require registration.\n"
        ),
        md(
            "## 2.3 Path helpers\n"
            "\n"
            "The notebooks can be run from the repository root **or** from "
            "`docs/workshop/`. These helpers find files relative to either "
            "location.\n"
        ),
        code(
            "from pathlib import Path\n"
            "\n"
            "ROOTS = (Path('.'), Path('../..'))   # candidate repo roots\n"
            "\n"
            "def repo_root():\n"
            "    return next((r for r in ROOTS if (r / 'src').is_dir()), Path('.'))\n"
            "\n"
            "def first_that_exists(*names):\n"
            "    for r in ROOTS:\n"
            "        for n in names:\n"
            "            c = r / n\n"
            "            if c.exists():\n"
            "                return c\n"
            "    return None\n"
        ),
        md(
            "## 2.4 Outputs — the canonical contract\n"
            "\n"
            "Both hydrodynamic engines write the **same six files**, so the web "
            "layer never cares which engine produced them:\n"
            "\n"
            "| File | Contents | Units |\n"
            "|------|----------|-------|\n"
            "| `tidal_power_density.tif` | Time-mean power density (primary product) | W/m² |\n"
            "| `max_current_speed.tif` | Max depth-averaged speed | m/s |\n"
            "| `bathymetry.tif` | Bathymetric depth | m |\n"
            "| `distance_to_coast.tif` | Distance to nearest coast | km |\n"
            "| `results.nc` | Time series (η, u, v, power) | mixed |\n"
            "| `hotspots.geojson` | Ranked sites ≥ threshold | W/m², m |\n"
            "\n"
            "Screening writes them to `output/`; a TELEMAC refinement writes the "
            "same names under `output/telemac/<region>/`.\n"
        ),
        code(
            "d = repo_root() / 'output'\n"
            "if d.is_dir():\n"
            "    print(f'[{d.resolve()}]')\n"
            "    for f in sorted(d.iterdir()):\n"
            "        if f.is_file():\n"
            "            print(f'  {f.name:<28s} {f.stat().st_size / 1e6:8.2f} MB')\n"
            "    for sub in ('telemac', 'screenshots'):\n"
            "        s = d / sub\n"
            "        if s.is_dir():\n"
            "            print(f'  {sub}/ ({len(list(s.iterdir()))} entries)')\n"
            "else:\n"
            "    print('output/ not present — run the screening model first')\n"
        ),
        md(
            "## 2.5 Read the power raster\n"
            "\n"
            "The GeoTIFFs are Cloud-Optimised, EPSG:4326, float32, with NaN "
            "nodata for land cells.\n"
        ),
        code(
            "import numpy as np\n"
            "\n"
            "try:\n"
            "    import rasterio\n"
            "except ImportError:\n"
            "    print('rasterio not installed — install it to read GeoTIFFs')\n"
            "else:\n"
            "    p = first_that_exists('output/tidal_power_density.tif')\n"
            "    if p is None:\n"
            "        print('no screening raster found (output/tidal_power_density.tif)')\n"
            "    else:\n"
            "        with rasterio.open(p) as src:\n"
            "            arr = src.read(1, masked=True)\n"
            "            print('source:', p)\n"
            "            print('bounds:', src.bounds)\n"
            "            print('crs   :', src.crs)\n"
            "            print('shape :', arr.shape)\n"
            "            v = arr.compressed()\n"
            "            if v.size:\n"
            "                print(f'min   : {v.min():.1f} W/m^2')\n"
            "                print(f'mean  : {v.mean():.1f} W/m^2')\n"
            "                print(f'max   : {v.max():.1f} W/m^2')\n"
            "                print(f'P95   : {np.percentile(v, 95):.1f} W/m^2')\n"
            "                print(f'cells >= 200 W/m^2: {int((arr >= 200).sum())}')\n"
        ),
        md(
            "## 2.6 Read the NetCDF time series\n"
            "\n"
            "`results.nc` holds hourly snapshots of η, staggered u/v, and power. "
            "We extract the time series at the raster cell nearest a chosen "
            "coordinate.\n"
        ),
        code(
            "try:\n"
            "    from netCDF4 import Dataset\n"
            "except ImportError:\n"
            "    print('netCDF4 not installed')\n"
            "else:\n"
            "    p = first_that_exists('output/results.nc')\n"
            "    if p is None:\n"
            "        print('no results.nc found')\n"
            "    else:\n"
            "        with Dataset(p) as nc:\n"
            "            lat = np.asarray(nc['lat'])\n"
            "            lon = np.asarray(nc['lon'])\n"
            "            tgt = (12.5, 122.5)\n"
            "            d2 = (lat - tgt[0]) ** 2 + (lon - tgt[1]) ** 2\n"
            "            r, c = np.unravel_index(np.argmin(d2), lat.shape)\n"
            "            times_h = np.asarray(nc['time']) / 3600.0\n"
            "            eta = np.asarray(nc['eta'][:, r, c])\n"
            "            pwr = np.asarray(nc['power_density'][:, r, c])\n"
            "            print('source      :', p)\n"
            "            print('nearest cell:', round(float(lat[r, c]), 3),\n"
            "                  round(float(lon[r, c]), 3))\n"
            "            print('window      : %.1f h, %d samples'\n"
            "                  % (times_h[-1] - times_h[0], times_h.size))\n"
            "            print(f'max |eta|    : {np.abs(eta).max():.2f} m')\n"
            "            print(f'mean power   : {pwr.mean():.1f} W/m^2')\n"
        ),
        md(
            "## 2.7 Read the hotspot GeoJSON\n"
            "\n"
            "`hotspots.geojson` is a `FeatureCollection` of points at cell "
            "centres with power density and depth properties.\n"
        ),
        code(
            "import json\n"
            "\n"
            "p = first_that_exists('output/hotspots.geojson')\n"
            "if p is None:\n"
            "    print('no hotspots.geojson found')\n"
            "else:\n"
            "    fc = json.loads(p.read_text())\n"
            "    print('source  :', p)\n"
            "    print('features:', len(fc['features']))\n"
            "    for f in fc['features'][:5]:\n"
            "        pr = f['properties']\n"
            "        print(f\"  {f['geometry']['coordinates'][0]:9.3f}, \"\n"
            "              f\"{f['geometry']['coordinates'][1]:7.3f}  \"\n"
            "              f\"{pr['power_density_Wm2']:7.1f} W/m^2  \"\n"
            "              f\"depth={pr['depth_m']:.0f} m\")\n"
        ),
        md(
            "## Next\n"
            "\n"
            "You can read every output and you know where the inputs come from. "
            "Move to [Notebook 3 — general workflow](3.general-workflow.ipynb) "
            "to see how they are produced end to end."
            + nav(prev="1.concept.ipynb", nxt="3.general-workflow.ipynb"),
        ),
    ]


# ---------------------------------------------------------------------------
# 3. general workflow
# ---------------------------------------------------------------------------
def n_workflow() -> list[dict]:
    return [
        md(
            header(
                "Notebook 3",
                "General workflow: screening → refinement → web",
                "The project has two hydrodynamic engines behind one output contract. "
                "This notebook walks the full pipeline and the commands that drive "
                "it. Detailed stages are in `../architecture/WORKFLOW.md`.",
            )
        ),
        md(
            "## Learning objectives\n"
            "\n"
            "- Explain the two-engine / one-contract design.\n"
            "- Name the stages: screening, hotspot clustering, TELEMAC cases, "
            "post-processing, web serving.\n"
            "- Know the CLI entry points for each stage.\n"
        ),
        md(
            "## 3.1 The pipeline\n"
            "\n"
            "```\n"
            "screening (python)  -->  hotspots.geojson\n"
            "        |\n"
            "        v\n"
            "cluster hotspots  -->  cases/region-001/{mesh.slf, mesh.cli, mesh.liq, case.cas}\n"
            "        |\n"
            "        v  (docker run flussplan/telemac telemac2d.py case.cas)\n"
            "TELEMAC-2D  -->  cases/region-001/r2d.slf\n"
            "        |\n"
            "        v\n"
            "postprocess  -->  output/telemac/region-001/{results.nc, *.tif, hotspots.geojson}\n"
            "        |\n"
            "        v\n"
            "web (Flask + MapLibre) serves screening and refinement alike\n"
            "```\n"
        ),
        img(
            "fig_pipeline.png",
            "The two-engine pipeline: screening, TELEMAC refinement, post-processing and web serving.",
        ),
        md(
            "## 3.2 Stage 1 — screening\n"
            "\n"
            "The Python solver runs over the whole Philippine bounding box and "
            "writes the canonical outputs, including `hotspots.geojson`:\n"
            "\n"
            "```bash\n"
            "python -m src.model.run\n"
            "```\n"
            "\n"
            "Override defaults with CLI flags, e.g. `--duration-days 15`, "
            "`--resolution-km 2.0`, `--output-dir output`, or `--engine telemac2d`."
        ),
        code(
            "import os\n"
            "import subprocess\n"
            "import sys\n"
            "from pathlib import Path\n"
            "\n"
            "cwd = next((c for c in (Path('.'), Path('../..')) if (c / 'src').is_dir()),\n"
            "           Path('.'))\n"
            "env = dict(os.environ, PYTHONPATH=str((cwd / 'src').resolve()))\n"
            "try:\n"
            "    r = subprocess.run([sys.executable, '-m', 'src.model.run', '--help'],\n"
            "                       capture_output=True, text=True, timeout=60,\n"
            "                       cwd=cwd, env=env)\n"
            "    print(r.stdout or r.stderr)\n"
            "except Exception as exc:\n"
            "    print('screening CLI not runnable here:', exc)\n"
        ),
        md(
            "## 3.3 Stage 2 — hotspot clustering and cases\n"
            "\n"
            "Screening hotspots are scattered points; a refinement needs a "
            "contiguous sub-domain. `cluster_hotspots` groups them "
            "(highest-power-first, greedy by great-circle distance) and expands "
            "each cluster with a margin. Explicit strait sites in "
            "`telemac2d.mesh.boundary.sites` take precedence over auto-clustering.\n"
            "\n"
            "```bash\n"
            "python -m model.telemac prepare --cases-dir cases\n"
            "```\n"
            "\n"
            "Each region becomes a self-contained case directory with mesh, "
            "boundary, liquid-boundary, and steering files plus manifests.\n"
        ),
        md(
            "## 3.4 Stage 3 — TELEMAC-2D run\n"
            "\n"
            "TELEMAC runs **only** inside a pinned public Docker image "
            "(`flussplan/telemac:v8-latest` by default). The runner mounts the "
            "case directory and invokes `telemac2d.py case.cas`:\n"
            "\n"
            "```bash\n"
            "python -m model.telemac run --case cases/region-001\n"
            "```\n"
        ),
        code(
            "cwd = next((c for c in (Path('.'), Path('../..')) if (c / 'src').is_dir()),\n"
            "           Path('.'))\n"
            "env = dict(os.environ, PYTHONPATH=str((cwd / 'src').resolve()))\n"
            "try:\n"
            "    r = subprocess.run([sys.executable, '-m', 'model.telemac', '--help'],\n"
            "                       capture_output=True, text=True, timeout=60,\n"
            "                       cwd=cwd, env=env)\n"
            "    print(r.stdout or r.stderr)\n"
            "except Exception as exc:\n"
            "    print('telemac CLI not runnable here:', exc)\n"
        ),
        md(
            "## 3.5 Stage 4 — post-processing\n"
            "\n"
            "`postprocess_case` rasterises the unstructured node fields onto a "
            "regular lon/lat grid and writes the **same canonical products**, "
            "tagged as `source=telemac2d`:\n"
            "\n"
            "```bash\n"
            "python -m model.telemac postprocess --case-dir cases/region-001 \\\n"
            "    --output-dir output/telemac/region-001\n"
            "```\n"
            "\n"
            "It also writes `reconciliation.json`, comparing the refinement with "
            "the parent screening in the same bounding box (see "
            "`../engines/RECONCILIATION.md`).\n"
        ),
        code(
            "for root in (Path('output/telemac'), Path('../../output/telemac')):\n"
            "    if root.is_dir():\n"
            "        for region in sorted(r for r in root.iterdir() if r.is_dir()):\n"
            "            files = sorted(p.name for p in region.iterdir() if p.is_file())\n"
            "            print(f'{region.name}: {files}')\n"
            "        break\n"
        ),
        md(
            "## 3.6 Stage 5 — web serving\n"
            "\n"
            "Because the output contract is identical, the Flask/MapLibre app "
            "serves screening and refinement outputs unchanged:\n"
            "\n"
            "```bash\n"
            "docker compose up -d --build    # http://localhost:8001\n"
            "```\n"
            "\n"
            "`GET /api/datasets` lists the screening dataset plus every TELEMAC "
            "region; dataset-aware endpoints accept `?region=region-001`.\n"
        ),
        md(
            "## Next\n"
            "\n"
            "The pipeline is clear. Move to "
            "[Notebook 4 — model](4.model.ipynb) for a hands-on screening run "
            "with the actual Python APIs."
            + nav(prev="2.data.ipynb", nxt="4.model.ipynb"),
        ),
    ]


# ---------------------------------------------------------------------------
# 4. model
# ---------------------------------------------------------------------------
def n_model() -> list[dict]:
    return [
        md(
            header(
                "Notebook 4",
                "Model: running the screening solver hands-on",
                "This notebook builds a small domain, runs the shallow-water solver, "
                "and writes canonical outputs. It uses the same public objects the "
                "CLI drives — `StructuredGrid`, `ShallowWaterSolver`, "
                "`make_synthetic_tidal_boundary`, and the output writers. See "
                "`../architecture/ARCHITECTURE.md` for the full design.",
            )
        ),
        md(
            "## Learning objectives\n"
            "\n"
            "- Build an Arakawa C-grid and understand its staggered layout.\n"
            "- Force it with a synthetic tidal boundary and integrate forward.\n"
            "- Compute power density, enforce the CFL condition, and write the "
            "canonical outputs.\n"
        ),
        md(
            "## 4.1 Imports\n"
            "\n"
            "Everything below degrades gracefully if the `model` package is not "
            "importable.\n"
        ),
        code(
            "import numpy as np\n"
            "\n"
            "try:\n"
            "    from model.grid import StructuredGrid\n"
            "    from model.solver import ShallowWaterSolver\n"
            "    from model.forcing import make_synthetic_tidal_boundary\n"
            "    from model.utils import speed, power_density, cfl_timestep\n"
            "    HAVE_MODEL = True\n"
            "except ImportError as exc:\n"
            "    HAVE_MODEL = False\n"
            "    print('model package not importable:', exc)\n"
            "    print('set PYTHONPATH=src or pip install -e .')\n"
        ),
        md(
            "## 4.2 Build a grid\n"
            "\n"
            "`StructuredGrid` stores η at cell centres, u on x-faces, and v on "
            "y-faces. Depth is positive down. We override the metre-based "
            "coordinates with degree-based ones so GeoTIFF output is valid.\n"
        ),
        code(
            "if HAVE_MODEL:\n"
            "    grid = StructuredGrid.from_uniform(nx=40, ny=25, dx=2000.0, dy=2000.0)\n"
            "    lon1 = np.linspace(120.0, 123.0, grid.nx)\n"
            "    lat1 = np.linspace(10.0, 12.5, grid.ny)\n"
            "    grid.lon, grid.lat = np.meshgrid(lon1, lat1)\n"
            "    grid.h[:] = 50.0\n"
            "    grid.h_u[:] = 50.0\n"
            "    grid.h_v[:] = 50.0\n"
            "    grid.open_boundary[:, 0] = True\n"
            "    grid.open_boundary[:, -1] = True\n"
            "    print('nx, ny        :', grid.nx, grid.ny)\n"
            "    print('dx, dy [m]    :', grid.dx, grid.dy)\n"
            "    print('wet cells     :', int(grid.mask.sum()))\n"
            "    print('open boundary :', int(grid.open_boundary.sum()), 'cells')\n"
        ),
        img(
            "fig_cgrid.png",
            "Arakawa C-grid: η at cell centres, u on x-faces, v on y-faces.",
        ),
        md(
            "## 4.3 CFL condition\n"
            "\n"
            "The explicit scheme is stable only if the time step respects the "
            "CFL limit. `cfl_timestep` computes it from the grid spacing and "
            "max depth; the config applies a safety factor.\n"
        ),
        code(
            "if HAVE_MODEL:\n"
            "    dt = cfl_timestep(grid.dx, grid.dy, grid.h_max, safety=0.5)\n"
            "    print(f'CFL timestep ~ {dt:.1f} s  (h_max = {grid.h_max:.0f} m)')\n"
        ),
        md(
            "## 4.4 Force and integrate\n"
            "\n"
            "`make_synthetic_tidal_boundary` builds an M2+S2 boundary; the "
            "solver prescribes η on the open-boundary cells and advances with "
            "the forward-backward scheme. We sample mean power and max speed "
            "inside a callback. This is a **short demo**, not a resource "
            "estimate — production runs last 15 days.\n"
        ),
        code(
            "if HAVE_MODEL:\n"
            "    bnd = make_synthetic_tidal_boundary(\n"
            "        int(grid.open_boundary.sum()), amplitude=0.8, constituents=['M2', 'S2'])\n"
            "    solver = ShallowWaterSolver(grid, cd=0.0025)\n"
            "    solver.set_open_boundary_eta(bnd)\n"
            "\n"
            "    state = {\n"
            "        'power_sum': np.zeros(grid.shape),\n"
            "        'speed_max': np.zeros(grid.shape),\n"
            "        'n': 0,\n"
            "    }\n"
            "\n"
            "    def cb(s, step):\n"
            "        if step % 10 == 0:\n"
            "            state['power_sum'] += s.compute_power_density()\n"
            "            np.maximum(state['speed_max'], speed(s.u, s.v),\n"
            "                       out=state['speed_max'])\n"
            "            state['n'] += 1\n"
            "        return None\n"
            "\n"
            "    solver.run(dt=30.0, duration=6 * 3600.0, callback=cb,\n"
            "               progress_interval=1e9)\n"
            "    power_mean = state['power_sum'] / max(state['n'], 1)\n"
            "    print('samples     :', state['n'])\n"
            "    print(f'max speed   : {state[\"speed_max\"].max():.2f} m/s')\n"
            "    print(f'max power   : {power_mean.max():.1f} W/m^2 (cell max)')\n"
        ),
        md(
            "## 4.5 Write canonical outputs\n"
            "\n"
            "The writers in `model.output` produce the same Cloud-Optimised "
            "GeoTIFFs and GeoJSON the real pipeline publishes. We write to "
            "`output/workshop-demo/` (gitignored).\n"
        ),
        code(
            "from pathlib import Path\n"
            "from model.output import (\n"
            "    write_mean_power_geotiff,\n"
            "    write_raster_geotiff,\n"
            "    write_hotspots_geojson,\n"
            ")\n"
            "\n"
            "if HAVE_MODEL:\n"
            "    root = next((c for c in (Path('.'), Path('../..')) if (c / 'src').is_dir()),\n"
            "                Path('.'))\n"
            "    out = root / 'output' / 'workshop-demo'\n"
            "    out.mkdir(parents=True, exist_ok=True)\n"
            "\n"
            "    power_layer = np.where(grid.mask, power_mean, np.nan)\n"
            "    speed_layer = np.where(grid.mask, state['speed_max'], np.nan)\n"
            "    write_mean_power_geotiff(grid, power_layer,\n"
            "                             str(out / 'tidal_power_density.tif'))\n"
            "    write_raster_geotiff(grid, speed_layer,\n"
            "                         str(out / 'max_current_speed.tif'),\n"
            "                         'max depth-averaged current speed (m/s)')\n"
            "    write_hotspots_geojson(grid, power_mean, threshold=1.0,\n"
            "                           path=str(out / 'hotspots.geojson'))\n"
            "    print('wrote outputs to', out)\n"
        ),
        code(
            "if HAVE_MODEL:\n"
            "    import json\n"
            "    for f in sorted(out.iterdir()):\n"
            "        print(f.name, f.stat().st_size, 'bytes')\n"
            "    fc = json.loads((out / 'hotspots.geojson').read_text())\n"
            "    print('hotspot features:', len(fc['features']))\n"
        ),
        md(
            "## 4.6 Tests\n"
            "\n"
            "The same physics is validated by the test suite (mass conservation, "
            "M2-forced channel, standing-wave period):\n"
            "\n"
            "```bash\n"
            "python -m pytest src/model/tests/\n"
            "```\n"
        ),
        md(
            "## Next\n"
            "\n"
            "The model works end to end. Move to "
            "[Notebook 5 — web](5.web.ipynb) to explore the Flask API and the "
            "map interface." + nav(prev="3.general-workflow.ipynb", nxt="5.web.ipynb"),
        ),
    ]


# ---------------------------------------------------------------------------
# 5. web
# ---------------------------------------------------------------------------
def n_web() -> list[dict]:
    return [
        md(
            header(
                "Notebook 5",
                "Web: the Flask API and map",
                "The web layer reads the canonical outputs and serves them through a "
                "Flask REST API to a MapLibre GL JS map. This notebook queries that "
                "API and plays with the turbine performance model. Source: "
                "`src/web/app.py` and `src/web/turbines.py`.",
            )
        ),
        md(
            "## Learning objectives\n"
            "\n"
            "- Start the web service (Docker or local Python).\n"
            "- Query layers, resource totals, time series, and hotspots.\n"
            "- Inspect the turbine dataset and power-curve model.\n"
        ),
        md(
            "## 5.1 Start the service\n"
            "\n"
            "The service is file-oriented: it reads GeoTIFFs, NetCDF, and "
            "GeoJSON from an output directory and serves tiles, queries, and "
            "downloads.\n"
            "\n"
            "```bash\n"
            "docker compose up -d --build        # http://localhost:8001\n"
            "# or locally:\n"
            "OUTPUT_DIR=output python -m src.web.app --host 0.0.0.0 --port 5000\n"
            "```\n"
            "\n"
            "`docker compose` maps host `8001` to container `5000`. If the "
            "service is not running, the cells below fall back to sample "
            "responses.\n"
        ),
        code(
            "%matplotlib inline\n"
            "import json\n"
            "import urllib.request\n"
            "\n"
            "BASE = 'http://localhost:8001'   # docker compose maps 8001 -> 5000\n"
            "\n"
            "def get_json(path):\n"
            "    with urllib.request.urlopen(BASE + path, timeout=3) as r:\n"
            "        return json.load(r)\n"
            "\n"
            "try:\n"
            "    layers = get_json('/api/layers')\n"
            "    res = get_json('/api/resource?min_power=200')\n"
            "    print('Connected to', BASE)\n"
            "    avail = [k for k, v in layers['layers'].items() if v.get('available')]\n"
            "    print('Available layers:', avail)\n"
            "    for k in ('n_cells', 'area_km2', 'mean_power_density',\n"
            "              'extractable_mw', 'aep_gwh_yr'):\n"
            "        print(f'  {k:22s}: {res.get(k)}')\n"
            "except Exception as exc:\n"
            "    print('Web service not running on', BASE, '->', exc)\n"
            "    print('Start it with:  docker compose up -d --build')\n"
            "    print('Sample /api/resource response:')\n"
            "    print(json.dumps({'n_cells': 1559, 'area_km2': 6120.4,\n"
            "                      'mean_power_density': 412.7,\n"
            "                      'extractable_mw': 2526.9,\n"
            "                      'aep_gwh_yr': 22136.1}, indent=2))\n"
        ),
        md(
            "With the service up, the map opens centred on the archipelago with "
            "the **mean power-density** layer as the default overlay — the "
            "time-mean ½ρU³ product of the screening run:\n"
            "\n"
            "![Tidal MSP map overview — mean power density](images/web-map-overview.png)\n"
        ),
        md(
            "## 5.2 Endpoints\n"
            "\n"
            "| Endpoint | Purpose |\n"
            "|----------|---------|\n"
            "| `/api/layers` | Layer metadata (bounds, stats, legend, availability) |\n"
            "| `/api/tiles/{layer}/{z}/{x}/{y}.png` | Colormapped raster tiles |\n"
            "| `/api/query?lat=&lon=&layer=` | Value at a point |\n"
            "| `/api/timeseries?lat=&lon=` | Tidal curve from `results.nc` |\n"
            "| `/api/hotspots?min=&limit=` | Ranked hotspots (GeoJSON) |\n"
            "| `/api/area_stats` | POST polygon → resource stats |\n"
            "| `/api/resource` | Filtered-domain totals (area / MW / AEP) |\n"
            "| `/api/turbines` · `/api/turbine_performance` | Turbine specs & yield |\n"
            "| `/api/download/{file}` | Download GeoTIFF / GeoJSON / NetCDF |\n"
            "\n"
            "Dataset-aware endpoints accept `?region=region-001` to target a "
            "TELEMAC refinement. `GET /api/datasets` lists what is available.\n"
        ),
        code(
            "try:\n"
            "    ts = get_json('/api/timeseries?lat=12.5&lon=122.5')\n"
            "    print('site   :', ts.get('lat'), ts.get('lon'))\n"
            "    print('summary:', ts.get('summary'))\n"
            "except Exception as exc:\n"
            "    print('timeseries not available:', exc)\n"
            "\n"
            "try:\n"
            "    hots = get_json('/api/hotspots?limit=3')\n"
            "    print('hotspots returned:', len(hots.get('features', [])))\n"
            "except Exception as exc:\n"
            "    print('hotspots not available:', exc)\n"
        ),
        md(
            "Toggling the other layers shows the same domain through the speed, "
            "bathymetry, and distance-to-coast rasters, and the hotspot panel "
            "ranks the sites that survived the screening threshold:\n"
            "\n"
            "![All raster layers overlaid on the map](images/web-map-all-layers.png)\n"
            "\n"
            "![Ranked hotspot sites in the side panel](images/web-hotspots.png)\n"
            "\n"
            "The **resource screening** panel (`/api/resource`) aggregates the "
            "cells that survive the min-power / depth / efficiency filters into "
            "suitable area, extractable MW, and AEP:\n"
            "\n"
            "![Resource screening totals in the side panel](images/web-resource-screening.png)\n"
        ),
        md(
            "## 5.3 Turbine dataset\n"
            "\n"
            "`src/web/turbines.py` ships a curated set of tidal in-stream "
            "turbines with a physically consistent power-curve model "
            "(cubic ramp from cut-in to rated speed).\n"
        ),
        code(
            "import numpy as np\n"
            "import matplotlib.pyplot as plt\n"
            "\n"
            "try:\n"
            "    from web.turbines import all_turbine_specs\n"
            "except ImportError as exc:\n"
            "    print('web.turbines not importable:', exc)\n"
            "else:\n"
            "    specs = all_turbine_specs()\n"
            "    print(f'{len(specs)} turbines loaded')\n"
            "    for t in specs[:5]:\n"
            "        print(f\"  {t['name']:<16s} {t['manufacturer']:<28s} \"\n"
            "              f\"{t['rated_power_kw']:>5.0f} kW  \"\n"
            "              f\"U_rated={t['rated_speed_mps']:.2f} m/s\")\n"
            "    top = specs[0]\n"
            "    pts = np.asarray(top['power_curve'])\n"
            "    plt.figure(figsize=(7, 4))\n"
            "    plt.plot(pts[:, 0], pts[:, 1], lw=2)\n"
            "    for x, lab in [(top['cut_in_mps'], 'cut-in'),\n"
            "                   (top['rated_speed_mps'], 'rated'),\n"
            "                   (top['cut_out_mps'], 'cut-out')]:\n"
            "        plt.axvline(x, ls=':', label=lab)\n"
            "    plt.xlabel('Current speed U (m/s)')\n"
            "    plt.ylabel('Power (kW)')\n"
            "    plt.title(f\"{top['name']} power curve\")\n"
            "    plt.legend()\n"
            "    plt.tight_layout()\n"
            "    plt.show()\n"
        ),
        img(
            "fig_turbine_curves.png",
            "Power curves of the curated real-turbine fleet.",
        ),
        md(
            "## 5.4 Site yield\n"
            "\n"
            "`/api/turbine_performance` (or `web.turbines.performance` directly) "
            "integrates a turbine's power series over a site's speed time series "
            "to give energy over the window, capacity factor, and AEP.\n"
        ),
        code(
            "try:\n"
            "    from web.turbines import all_turbine_specs, performance\n"
            "    spec = all_turbine_specs()[0]\n"
            "    # Synthetic 2-day speed series at a lively site\n"
            "    rng = np.random.default_rng(3)\n"
            "    t_h = np.linspace(0, 48, 200)\n"
            "    speed_ts = 2.0 + 0.6 * np.sin(2 * np.pi * t_h / 12.42) + \\\n"
            "               0.15 * rng.standard_normal(t_h.size)\n"
            "    perf = performance(spec, [float(x) for x in speed_ts],\n"
            "                        [float(x) for x in t_h])\n"
            "    print(f\"{spec['name']} over a 2-day synthetic series:\")\n"
            "    print(f\"  capacity factor : {perf['capacity_factor'] * 100:.1f} %\")\n"
            "    print(f\"  mean output     : {perf['mean_output_kw']:.1f} kW\")\n"
            "    print(f\"  AEP             : {perf['aep_gwh_yr']:.3f} GWh/yr\")\n"
            "    print(f\"  % time at rated : {perf['pct_time_at_rated']:.1f} %\")\n"
            "except ImportError as exc:\n"
            "    print('web.turbines not importable:', exc)\n"
        ),
        md(
            "In the map UI the same workflow is one click: the **site "
            "inspector** shows the location's stats, the tidal curve from "
            "`results.nc`, and the per-turbine yield for the selected device:\n"
            "\n"
            "![Site inspector: stats, tidal curve, and turbine performance](images/web-site-inspector.png)\n"
        ),
        md(
            "## 5.5 Next phase — continuous modelling\n"
            "\n"
            "Everything so far treats the model as a **snapshot**: the API "
            "serves whatever `output/` contains at request time. A production "
            "web service should become a **living system** that ingests new "
            "bathymetry and tidal observations, re-runs the models, and "
            "refreshes the map without a human regenerating every layer. The "
            "pieces to add are ingestion, storage, orchestration, and "
            "refresh:\n"
            "\n"
            "| Concern | Open-source tooling |\n"
            "|---------|---------------------|\n"
            "| Instrument layer | Tidal gauges, ADCPs, and floats report over MQTT (Eclipse Mosquitto) or the OGC SensorThings API (FROST-Server) |\n"
            "| Tide-gauge feeds | UNESCO/IOC Sea Level Station Monitoring Facility, NOAA CO-OPS API, IOOS Sensor Observation Service, GLOSS networks |\n"
            "| Harmonic analysis & QC | pyTMD / utide for constituents, `cf-xarray` + pydap to read remote NetCDF, custom QA gates |\n"
            "| Storage | TimescaleDB or InfluxDB for observations; Zarr / Kerchunk + STAC (stac-fastapi, pgSTAC) for rasters |\n"
            "| ETL & scheduling | Apache Airflow / Prefect / Dagster; dbt for repeatable transformations |\n"
            "| Serving | the existing Flask API + MapLibre map; Grafana for operational dashboards |\n"
            "\n"
            "A realistic refresh cycle: new **bathymetry** arrives from GEBCO / "
            "EMODnet or a multibeam survey (processed with MB-System) and the "
            "screening solver re-runs on the updated grid; new **tidal** "
            "observations from gauges and IoT sensors are harmonically analysed "
            "and folded back into the boundary forcing. The map, time series, "
            "and hotspots then drift toward measured reality instead of a "
            "one-off snapshot — and the API needs no changes, because the web "
            "layer is file-oriented and cache-invalidates on file mtime.\n"
            "\n"
            "The cell below queries a public tide-gauge feed (NOAA CO-OPS) to "
            "show what a live ingestion step looks like. It falls back to a "
            "synthetic M2 curve when the network is unavailable.\n"
        ),
        code(
            "import json\n"
            "import urllib.request\n"
            "\n"
            "# NOAA CO-OPS water-level API (open, free):\n"
            "# https://api.tidesandcurrents.noaa.gov/api/prod/\n"
            "station = '8724580'   # Key West, FL — swap for a local gauge\n"
            "url = ('https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?'\n"
            "       f'date=recent&station={station}&product=water_level&'\n"
            "       'units=metric&time_zone=gmt&format=json&interval=6')\n"
            "\n"
            "try:\n"
            "    with urllib.request.urlopen(url, timeout=4) as r:\n"
            "        obs = json.load(r)['data']\n"
            "    print(f'live water levels @ station {station}: {len(obs)} samples')\n"
            "    for o in obs[:3]:\n"
            "        print(f\"  t={o['t']}  z={o['v']} m\")\n"
            "except Exception as exc:\n"
            "    print('live gauge not reachable ->', exc)\n"
            "    print('synthetic M2 water level instead:')\n"
            "    t_h = np.arange(0.0, 12.0, 0.1)\n"
            "    for t in t_h[::12]:\n"
            "        print(f'  t={t:4.1f} h  z={0.5 * np.cos(2 * np.pi * t / 12.42):+.2f} m')\n"
        ),
        md(
            "## 5.6 Establishing a turbine array\n"
            "\n"
            "§ 5.4 sized **one** turbine at a site. An array multiplies that "
            "into a field of devices, and the layout is an engineering "
            "decision, not a gridding afterthought:\n"
            "\n"
            "- **Spacing** — devices sit several rotor diameters apart so wakes "
            "re-energise before the next rotor: typically **3–5D laterally** "
            "and **10–20D streamwise** (D = rotor diameter). Tighter spacing "
            "raises blockage and output per m² but cuts efficiency and "
            "increases loads.\n"
            "- **Clearance** — the rotor tip needs a draft below the surface "
            "and a gap above the seabed; that rules out parts of even a "
            "high-power-density cell.\n"
            "- **Tidal asymmetry** — flood and ebb often differ in speed and "
            "direction, so rows are oriented along the dominant flow axis and "
            "devices are pitched or yawed to harvest both phases.\n"
            "- **Blockage** — the array area ÷ channel cross-section should "
            'stay at a few percent or the devices "choke" the strait and '
            "change the very flow they harvest.\n"
            "- **Feedback** — a dense array slows the channel (a momentum "
            "sink). The screening solver can represent a first pass by raising "
            "the local drag coefficient `cd` in the array cells; later stages "
            "use actuator-disk / CFD and farm-layout optimisation (OpenFAST, "
            "FLORIS, topfarm).\n"
            "\n"
            "The cell below packs devices into a rectangular lease block at "
            "4D × 15D spacing and reports installed capacity and annual "
            "energy.\n"
        ),
        code(
            "try:\n"
            "    from web.turbines import all_turbine_specs\n"
            "    spec = all_turbine_specs()[0]   # largest turbine\n"
            "except ImportError:\n"
            "    spec = {'name': 'Kairyu', 'rated_power_kw': 3000.0,\n"
            "            'rotor_diameter_m': 20.0, 'n_rotors': 2}\n"
            "\n"
            "D = spec['rotor_diameter_m']\n"
            "S_lat, S_str = 4.0 * D, 15.0 * D    # lateral / streamwise spacing\n"
            "swept = spec['n_rotors'] * np.pi * (D / 2) ** 2\n"
            "\n"
            "# A 2 km x 1 km lease block, flow along the 2 km axis\n"
            "W, L = 2000.0, 1000.0\n"
            "n_col = max(int(W // S_lat), 1)\n"
            "n_row = max(int(L // S_str), 1)\n"
            "n_turb = n_col * n_row\n"
            "installed_mw = n_turb * spec['rated_power_kw'] / 1e3\n"
            "cf = 0.30                            # planning-level capacity factor\n"
            "aep_gwh = installed_mw * cf * 8760.0\n"
            "\n"
            "print(f\"turbine        : {spec['name']} (D = {D:.0f} m)\")\n"
            "print(f'spacing        : {S_lat:.0f} m lateral x {S_str:.0f} m streamwise')\n"
            "print(f'layout         : {n_col} x {n_row} = {n_turb} devices')\n"
            "print(f'installed      : {installed_mw:.1f} MW')\n"
            "print(f'AEP @ CF={cf:.0%} : {aep_gwh:.0f} GWh/yr')\n"
            "print(f'blockage check : {n_turb * swept / (W * L):.2%} of lease area')\n"
        ),
        md(
            "The same area can be assessed interactively in the web app: the "
            "**draw tool** turns a polygon into the cell count, area, "
            "power-density stats, and extractable MW/AEP for that exact "
            "footprint — the geometry-level equivalent of the array block "
            "above:\n"
            "\n"
            "![Polygon site assessment with area statistics](images/web-polygon-assessment.png)\n"
        ),
        md(
            "## 5.7 Beyond physics: environment, law, and suitability\n"
            "\n"
            "Hotspots are physics; a **deployable** site is physics **and** "
            "society. The map becomes a marine spatial planning (MSP) tool "
            "only once it folds in other factors:\n"
            "\n"
            "- **Protected areas** — marine protected areas (MPAs), national "
            "parks, and no-go zones, from the UNEP-WCMC World Database on "
            "Protected Areas (WDPA) / Protected Planet, rasterised into a "
            "suitability layer.\n"
            "- **Other ocean uses** — shipping lanes, fishing grounds (Global "
            "Fishing Watch), submarine cables, military zones, and customary "
            "use by coastal communities.\n"
            "- **Ecosystems & species** — coral reefs, seagrass, dugong, "
            "cetaceans and migratory corridors (IUCN Red List ranges); "
            "construction and operation noise and seabed disturbance.\n"
            "- **Law & process** — Philippine practice: the NIPAS Act "
            "(RA 7586) for MPAs, the Fisheries Code (RA 8550/10654), DOE "
            "service contracts and permitting for ocean energy, and an "
            "Environmental Impact Statement / Certificate (EIS/ECC) through "
            "DENR-EMB before construction, plus public consultation.\n"
            "\n"
            "Open-source tooling: **geopandas / shapely / rasterio** for the "
            "overlay, **QGIS** for interactive review, and **Marxan / "
            "prioritizr** for formal conservation-target spatial planning. "
            "The output is a **suitability score** per cell that multiplies "
            "the resource layer by feasibility masks — the multi-criteria "
            "decision-analysis step the MSP literature calls for.\n"
            "\n"
            "The cell below loads the hotspots and applies a quick "
            'suitability filter: anything inside a sample "protected" zone '
            "is excluded and the survivors are re-ranked by power density. It "
            "falls back to sample data when the model output is not on disk.\n"
        ),
        code(
            "import json\n"
            "from pathlib import Path\n"
            "\n"
            "root = next((c for c in (Path('.'), Path('../..'))\n"
            "             if (c / 'src').is_dir()), Path('.'))\n"
            "hs_path = root / 'output' / 'hotspots.geojson'\n"
            "\n"
            "try:\n"
            "    fc = json.loads(hs_path.read_text())\n"
            "    sites = fc['features']\n"
            "except Exception:\n"
            "    print('hotspots.geojson not found; using sample sites')\n"
            "    def site(lon, lat, power):\n"
            "        return {'geometry': {'coordinates': [lon, lat]},\n"
            "                'properties': {'power_density_Wm2': power}}\n"
            "    sites = [site(122.6, 12.8, 620.0), site(122.3, 12.5, 300.0),\n"
            "             site(121.9, 12.1, 520.0)]\n"
            "\n"
            "# Sample protected-zone rectangle (lon/lat). Replace with real\n"
            "# WDPA polygons in production.\n"
            "prot = {'west': 122.4, 'east': 122.7, 'south': 12.4, 'north': 12.6}\n"
            "\n"
            "def inside_protected(s):\n"
            "    lon, lat = s['geometry']['coordinates']\n"
            "    return (prot['west'] <= lon <= prot['east']\n"
            "            and prot['south'] <= lat <= prot['north'])\n"
            "\n"
            "ranked = sorted((s for s in sites if not inside_protected(s)),\n"
            "                key=lambda s: s['properties'].get('power_density_Wm2', 0),\n"
            "                reverse=True)\n"
            "excluded = sum(inside_protected(s) for s in sites)\n"
            "print(f'{len(sites)} hotspot(s), {excluded} inside protected zone')\n"
            "for s in ranked[:3]:\n"
            "    lon, lat = s['geometry']['coordinates']\n"
            "    print(f\"  P = {s['properties'].get('power_density_Wm2', 0):6.1f} W/m²  \"\n"
            '          f"at ({lat:.2f}, {lon:.2f})")\n'
        ),
        md(
            "## Next\n"
            "\n"
            "You have seen the whole stack. Move to "
            "[Notebook 6 — consolidation](6.consolidation.ipynb) to recap, run "
            "a final stack check, and try the exercises."
            + nav(prev="4.model.ipynb", nxt="6.consolidation.ipynb"),
        ),
    ]


# ---------------------------------------------------------------------------
# 6. consolidation
# ---------------------------------------------------------------------------
def n_consolidation() -> list[dict]:
    return [
        md(
            header(
                "Notebook 6",
                "Consolidation: recap, stack check, and exercises",
                "The final notebook ties the series together: a single stack check, "
                "a review of how the engines reconcile, suggested exercises, and "
                "pointers to the deeper documentation.",
            )
        ),
        md(
            "## Recap\n"
            "\n"
            "| Notebook | Covered |\n"
            "|----------|---------|\n"
            "| 0 · setup | Environment, install, data |\n"
            "| 1 · concept | Tidal physics, ½ρU³, turbine mechanics, hotspots |\n"
            "| 2 · data | Inputs, config, six canonical outputs |\n"
            "| 3 · general-workflow | Screening → TELEMAC → web pipeline |\n"
            "| 4 · model | Grid, solver, forcing, outputs |\n"
            "| 5 · web | Flask API, map, turbines |\n"
            "| 6 · consolidation | This notebook |\n"
        ),
        md(
            "## 6.1 Final stack check\n"
            "\n"
            "Run one cell that verifies the whole stack: Python, the `model` "
            "package, `web.turbines`, the configuration, and the screening "
            "output.\n"
        ),
        code(
            "import json\n"
            "from pathlib import Path\n"
            "\n"
            "report = {}\n"
            "\n"
            "try:\n"
            "    import numpy as np\n"
            "    report['numpy'] = np.__version__\n"
            "except ImportError:\n"
            "    report['numpy'] = 'missing'\n"
            "\n"
            "try:\n"
            "    from model.grid import StructuredGrid\n"
            "    report['model pkg'] = 'ok'\n"
            "except ImportError:\n"
            "    report['model pkg'] = 'missing (PYTHONPATH=src)'\n"
            "\n"
            "try:\n"
            "    from web.turbines import all_turbine_specs\n"
            "    report['web.turbines'] = f'{len(all_turbine_specs())} turbines'\n"
            "except ImportError:\n"
            "    report['web.turbines'] = 'missing'\n"
            "\n"
            "try:\n"
            "    from model.config import load_config\n"
            "    report['engine'] = load_config()['engine']['name']\n"
            "except Exception as exc:\n"
            "    report['engine'] = f'error ({exc})'\n"
            "\n"
            "root = next((c for c in (Path('.'), Path('../..')) if (c / 'src').is_dir()),\n"
            "            Path('.'))\n"
            "report['power raster'] = (\n"
            "    'present' if (root / 'output' / 'tidal_power_density.tif').exists()\n"
            "    else 'not found')\n"
            "\n"
            "print(json.dumps(report, indent=2))\n"
        ),
        md(
            "## 6.2 How the engines reconcile\n"
            "\n"
            "The Python screening is the **nationwide view**; each TELEMAC-2D run "
            "is the zoomed-in view of a strait. The two are kept consistent by "
            "treating TELEMAC as a nested child of the screening run:\n"
            "\n"
            "- **Boundary:** sample the parent's own η at the refinement's liquid "
            "points (one-way nesting).\n"
            "- **Bathymetry:** inherit the parent depths/mask at mesh resolution "
            "(`bathymetry_source: parent`).\n"
            "- **Friction:** harmonise Chezy with the screening drag "
            "(`friction_coefficient ≈ sqrt(g / cd)`).\n"
            "- **Comparison:** `reconciliation.json` records max power/speed, "
            "p95 and median, and their parent ratios, with acceptance windows.\n"
            "\n"
            "Full detail: `../engines/RECONCILIATION.md` and "
            "`../engines/TELEMAC.md`.\n"
        ),
        md(
            "## 6.3 Exercises\n"
            "\n"
            "Try these on your own:\n"
            "\n"
            "1. **Resolution sensitivity** — rerun Notebook 4 with `dx = 1000 m` "
            "and compare the max speed. Does halving the cell size change the "
            "result as expected?\n"
            "2. **Friction sensitivity** — rerun with `cd = 0.002` and "
            "`cd = 0.004`. Which runs faster/slower, and why?\n"
            "3. **Constituent set** — add S2 to a synthetic boundary and check "
            "the spring–neap envelope appears in the sampled mean.\n"
            "4. **API** — with the web service running, POST a polygon to "
            "`/api/area_stats` and compare area/MW/AEP with `/api/resource`.\n"
            "5. **Turbines** — for the site series in Notebook 5, find which "
            "turbine gives the highest capacity factor and explain why.\n"
        ),
        md(
            "## 6.4 Self-check\n"
            "\n"
            "<details>\n"
            "<summary>What makes a strait a hotspot?</summary>\n"
            "\n"
            "A narrow, deep channel connecting basins with different tidal phases "
            "concentrates the flow (mass conservation), and power scales as the "
            "cube of speed.\n"
            "</details>\n"
            "\n"
            "<details>\n"
            "<summary>Why is the primary map layer a *time-mean* power density?</summary>\n"
            "\n"
            "Energy yield depends on the full spring–neap envelope; a single "
            "instant or peak over-states the resource. Averaging over ≥ 15 days "
            "is a better proxy for annual energy.\n"
            "</details>\n"
            "\n"
            "<details>\n"
            "<summary>Why can the same web app serve screening and TELEMAC outputs?</summary>\n"
            "\n"
            "Both engines write the same canonical files (`results.nc`, the four "
            "GeoTIFFs, `hotspots.geojson`), so the API is engine-agnostic.\n"
            "</details>\n"
        ),
        md(
            "## 6.5 Further reading\n"
            "\n"
            "- `../README.md` — documentation index.\n"
            "- `../concepts/MODEL.md` — full physics and methodology.\n"
            "- `../architecture/ARCHITECTURE.md` — integrated technical guide.\n"
            "- `../engines/TELEMAC.md`, `../engines/CASE_AUTHORING.md`, "
            "`../engines/POSTPROCESSING.md`, `../engines/RECONCILIATION.md` — "
            "refinement backend.\n"
            "- `../operations/TROUBLESHOOTING.md` — operational fixes.\n"
            "- `../notebooks/EXPLAINER.ipynb` and `../notebooks/workshop.ipynb` — "
            "alternative walkthroughs.\n"
            "- `../../src/README.md` — dataset acquisition and step-by-step setup.\n"
            + nav(prev="5.web.ipynb"),
        ),
    ]


# ---------------------------------------------------------------------------
# index README
# ---------------------------------------------------------------------------
INDEX = """# Tidal-OSS Workshop

A linear, runnable workshop series that consolidates the standalone
documentation into one path. Each notebook teaches one slice of the stack and
ends pointing to the next.

## How to use

Run from the repository root (or open `docs/workshop/` in Jupyter):

```bash
jupyter notebook docs/workshop/
```

Install the environment first (see [Notebook 0](0.setup.ipynb) and
[`../AGENTS.md`](../AGENTS.md)); an editable install (`pip install -e .`) makes
the `model` and `web` packages importable without `PYTHONPATH`.

Code cells are defensive: if an optional package or a generated output is
missing, they print a helpful message instead of crashing.

## Web version

The generator also builds a single-page HTML view of all seven notebooks
(markdown, code, and figures rendered; no execution) at
`site/index.html` — open it directly in a browser and pick notebooks from
the left-hand sidebar. Rebuild standalone with
`python3 scripts/build_workshop_website.py`. Rendering libraries load from a
CDN, so viewing requires an internet connection.

## The series

| # | Notebook | Covers |
|---|----------|--------|
| 0 | [setup](0.setup.ipynb) | Environment, install, data, config check |
| 1 | [concept](1.concept.ipynb) | Tidal physics, ½ρU³, turbine mechanics, hotspots |
| 2 | [data](2.data.ipynb) | Data portals & repositories, inputs, configuration, six canonical outputs |
| 3 | [general-workflow](3.general-workflow.ipynb) | Screening → TELEMAC → web pipeline |
| 4 | [model](4.model.ipynb) | Hands-on screening solver and output writers |
| 5 | [web](5.web.ipynb) | Flask API, map, turbine performance, next-phase roadmap |
| 6 | [consolidation](6.consolidation.ipynb) | Stack check, exercises, further reading |

## Relationship to the rest of `docs/`

The workshop is a guided path; the reference documentation provides depth:

- Physics & methodology: [`../concepts/MODEL.md`](../concepts/MODEL.md)
- Architecture & design: [`../architecture/ARCHITECTURE.md`](../architecture/ARCHITECTURE.md)
- Workflow: [`../architecture/WORKFLOW.md`](../architecture/WORKFLOW.md)
- TELEMAC backend: [`../engines/TELEMAC.md`](../engines/TELEMAC.md) and friends
- Operations: [`../operations/TROUBLESHOOTING.md`](../operations/TROUBLESHOOTING.md)

## Maintenance

These notebooks are generated by `scripts/generate_workshop_series.py`. Edit
the generator, then run `python3 scripts/generate_workshop_series.py` to
regenerate them. The same command regenerates the `site/` HTML view (via
`scripts/build_workshop_website.py`); `site/` is a build artifact and is not
hand-edited.
"""


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, cells in (
        ("0.setup.ipynb", n_setup()),
        ("1.concept.ipynb", n_concept()),
        ("2.data.ipynb", n_data()),
        ("3.general-workflow.ipynb", n_workflow()),
        ("4.model.ipynb", n_model()),
        ("5.web.ipynb", n_web()),
        ("6.consolidation.ipynb", n_consolidation()),
    ):
        _write(name, cells)
    index = OUT_DIR / "README.md"
    index.write_text(INDEX, encoding="utf-8")
    print(f"wrote {index}")
    from build_workshop_website import build as build_site

    build_site(OUT_DIR)
    print("Done.")


if __name__ == "__main__":
    main()
