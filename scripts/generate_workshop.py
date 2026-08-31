"""Generate docs/notebooks/workshop.ipynb — a Jupyter slide deck for the
tidal-oss workshop.

Run from the repo root:  python3 scripts/generate_workshop.py
The deck covers: Data, Solution Architecture, Processing, Web Service, Features,
with live code demos that prefer the repo's own packages and fall back to
built-in implementations when those packages are unavailable.
"""
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT = REPO_ROOT / "docs" / "notebooks" / "workshop.ipynb"

cells = []


def md(text, st="slide"):
    cells.append({
        "cell_type": "markdown",
        "metadata": {"slideshow": {"slide_type": st}},
        "source": text,
    })


def code(text, st="slide"):
    cells.append({
        "cell_type": "code",
        "execution_count": None,
        "metadata": {"slideshow": {"slide_type": st}},
        "outputs": [],
        "source": text,
    })


# --------------------------------------------------------------------------
# 1. Title
# --------------------------------------------------------------------------
md(
    "# Tidal-Current Energy in the Philippines\n"
    "## A Workshop on the Open-Source Screening & Visualisation Stack\n"
    "\n"
    "Marine spatial planning (MSP) for tidal in-stream energy — from raw "
    "bathymetry and tidal harmonics to an interactive web map.\n"
    "\n"
    "*Two-phase workflow + high-resolution refinement:*\n"
    "\n"
    "1. **Screening** — a 2-D depth-averaged shallow-water solver in Python/NumPy.\n"
    "2. **Web** — a Flask + MapLibre GL JS tool to explore the resource.\n"
    "3. **Refinement** — TELEMAC-2D on the top hotspots (optional, engine-agnostic).\n"
    "\n"
    "MIT licensed · https://github.com/anomalyco/tidal-oss"
)

# --------------------------------------------------------------------------
# 2. Agenda
# --------------------------------------------------------------------------
md(
    "## What we'll cover\n"
    "\n"
    "| # | Topic |\n"
    "|---|-------|\n"
    "| 1 | **The Data** — inputs we ingest and the outputs we publish |\n"
    "| 2 | **Solution Architecture** — how the pieces fit together |\n"
    "| 3 | **Processing** — the shallow-water model & power-density maths |\n"
    "| 4 | **Web Service** — the Flask/MapLibre API and map |\n"
    "| 5 | **Features** — what the MSP tool can do |\n"
    "\n"
    "Each section ends with a **live code demo** you can run right here."
)

# --------------------------------------------------------------------------
# 3. Data
# --------------------------------------------------------------------------
md(
    "# 1 · The Data\n"
    "\n"
    "Every assessment starts with two kinds of geospatial data:\n"
    "\n"
    "- **Bathymetry** — how deep the water is (drives friction & funnelling).\n"
    "- **Tidal forcing** — how the sea surface rises & falls at the open boundaries.\n"
    "\n"
    "Plus a **land mask** so we never compute currents on dry land."
)

md(
    "## Inputs we ingest\n"
    "\n"
    "| Input | Source | Role |\n"
    "|-------|--------|------|\n"
    "| Bathymetry | **GEBCO 2026** NetCDF | Seabed depth *h* (m, positive down) |\n"
    "| Tidal harmonics | **GOT4.10c** / FES2014 / TPXO9 (or synthetic) | M₂, S₂, K₁, O₁ amplitudes & phases |\n"
    "| Land mask | **Philippines landmass GeoJSON** (from OSM / GADM) | Mark dry cells |\n"
    "\n"
    "The model regrids everything onto one uniform **Arakawa C-grid** "
    "(~2 km) covering the Philippine bounding box 116–128°E, 4–22°N, and applies "
    "the CFL stability condition to pick the time step automatically."
, "subslide")

md(
    "## Outputs we publish\n"
    "\n"
    "Six canonical files in `output/` (the *output contract* shared by the "
    "screening solver and TELEMAC-2D):\n"
    "\n"
    "| File | Contents |\n"
    "|------|----------|\n"
    "| `tidal_power_density.tif` | Time-mean power density **[W/m²]** (primary product) |\n"
    "| `max_current_speed.tif` | Max depth-averaged speed **[m/s]** |\n"
    "| `bathymetry.tif` | Bathymetric depth **[m]** |\n"
    "| `distance_to_coast.tif` | Distance to nearest coast **[km]** |\n"
    "| `results.nc` | Time series (η, u, v, power) — NetCDF |\n"
    "| `hotspots.geojson` | Ranked sites with power ≥ 200 W/m² |\n"
, "subslide")

# --------------------------------------------------------------------------
# Demo A — data visualisation
# --------------------------------------------------------------------------
code(
    "import numpy as np\n"
    "import matplotlib.pyplot as plt\n"
    "\n"
    "def _find_power_raster():\n"
    "    # Locate the canonical screening product whether the notebook is run from\n"
    "    # the repo root or from docs/notebooks/.\n"
    "    from pathlib import Path\n"
    "    candidates = [\n"
    "        Path('output/tidal_power_density.tif'),\n"
    "        Path('../../../output/tidal_power_density.tif'),\n"
    "    ]\n"
    "    return next((p for p in candidates if p.exists()), None)\n"
    "\n"
    "def load_power_field():\n"
    "    # Prefer the real screening output; otherwise synthesise a realistic field.\n"
    "    try:\n"
    "        import rasterio\n"
    "        p = _find_power_raster()\n"
    "        if p is not None:\n"
    "            with rasterio.open(p) as src:\n"
    "                arr = np.ma.masked_invalid(src.read(1).astype(float))\n"
    "            return np.asarray(arr), str(p), True\n"
    "    except Exception as exc:\n"
    "        print('rasterio / real data unavailable:', exc)\n"
    "    # Synthetic: a noisy shelf with two high-power straits.\n"
    "    rng = np.random.default_rng(7)\n"
    "    ny, nx = 120, 200\n"
    "    x = np.linspace(0, 1, nx); y = np.linspace(0, 1, ny)\n"
    "    X, Y = np.meshgrid(x, y)\n"
    "    base = rng.lognormal(mean=4.0, sigma=0.9, size=(ny, nx)) * 0.15\n"
    "    s1 = 1600 * np.exp(-((X-0.30)**2)/0.002 - ((Y-0.5)**2)/0.20)\n"
    "    s2 = 1100 * np.exp(-((X-0.68)**2)/0.0015 - ((Y-0.35)**2)/0.12)\n"
    "    return np.clip(base + s1 + s2, 0, None), 'synthetic (straits @ x=0.30, 0.68)', False\n"
    "\n"
    "field, src_label, is_real = load_power_field()\n"
    "print('source :', src_label)\n"
    "print(f'min={field.min():.1f}  mean={field.mean():.1f}  max={field.max():.1f} W/m^2')\n"
    "print(f'P95   ={np.percentile(field,95):.1f} W/m^2')\n"
    "print('hotspot cells (>=200 W/m^2):', int((field>=200).sum()))\n"
    "\n"
    "plt.figure(figsize=(9, 4.5))\n"
    "im = plt.imshow(field, origin='lower', cmap='inferno',\n"
    "               vmin=0, vmax=max(300, float(np.percentile(field, 99))))\n"
    "plt.colorbar(im, label='Power density (W/m^2)')\n"
    "plt.title('Tidal power density - screening output')\n"
    "plt.xlabel('longitude index'); plt.ylabel('latitude index')\n"
    "plt.show()"
)

# --------------------------------------------------------------------------
# 4. Architecture
# --------------------------------------------------------------------------
md(
    "# 2 · Solution Architecture\n"
    "\n"
    "The design philosophy is **fail fast, fail cheap**: a coarse model finds the "
    "obvious hotspots, then only those sites get the expensive high-resolution "
    "treatment.\n"
    "\n"
    "```\n"
    "Phase A: Screening                          Phase B: Web Visualisation\n"
    "=================================          ================================\n"
    "\n"
    " GEBCO  --\u2502                                          Flask (REST API)\n"
    " GOT4.10c -\u2504-- model.run --\u2502-- results.nc               |\n"
    "               -\u2502-- tidal_power_density.tif          MapLibre GL JS\n"
    "               -\u2502-- hotspots.geojson\n"
    "```\n"
    "\n"
    "TELEMAC-2D (Phase C) refines the top hotspots and writes the **same six "
    "files**, so the web app is engine-agnostic."
)

md(
    "## The screening \u2192 refinement cascade\n"
    "\n"
    "```\n"
    "Coarse Python model (this one)\n"
    "        |\n"
    "        v\n"
    "   Sites with  P_mean > 200 W/m^2   (hotspots.geojson)\n"
    "        |\n"
    "        v\n"
    "   High-resolution TELEMAC-2D unstructured mesh\n"
    "        |\n"
    "        v\n"
    "   Turbine-array CFD / actuator-disk model\n"
    "        |\n"
    "        v\n"
    "   Geophysical / environmental surveys  ->  Pilot deployment\n"
    "```\n"
    "\n"
    "Key idea: the screening model is **deliberately conservative** (coarse "
    "resolution + depth-averaging under-estimates speed), so any site it flags "
    "is almost certainly worth a second look."
, "subslide")

# --------------------------------------------------------------------------
# 5. Processing
# --------------------------------------------------------------------------
md(
    "# 3 · Processing\n"
    "\n"
    "At the heart of Phase A is the **2-D depth-averaged shallow-water solver** "
    "(`src/model/`). It integrates the SWE on an Arakawa C-grid with a "
    "forward-backward time stepper.\n"
    "\n"
    "**Continuity (mass):**\n"
    "$$\\frac{\\partial \\eta}{\\partial t} + \\frac{\\partial}{\\partial x}(h u) + "
    "\\frac{\\partial}{\\partial y}(h v) = 0$$\n"
    "\n"
    "**Momentum (Newton, linearised):**\n"
    "$$\\frac{\\partial u}{\\partial t} = -g\\,\\frac{\\partial \\eta}{\\partial x} "
    "- \\frac{C_d}{h}\\,|u|\\,u + f v$$\n"
    "\n"
    "Pressure gradient accelerates the flow; quadratic bottom friction "
    "($C_d\\,|u|u/h$) is the dominant energy sink; Coriolis ($f v$) matters at "
    "basin scale."
)

md(
    "## From current to power: the \u00bd\u03c1U\u00b3 law\n"
    "\n"
    "A tidal turbine is a kinetic-energy converter. The **instantaneous power per "
    "unit swept area** is:\n"
    "\n"
    "$$P = \\tfrac{1}{2}\\,\\rho\\,U^{3} \\qquad [\\text{W/m}^2]$$\n"
    "\n"
    "with $\\rho = 1025$ kg/m\u00b3 (seawater) and $U = \\sqrt{u^2+v^2}$.\n"
    "\n"
    "> The **cubic** dependence is the defining feature: doubling the current "
    "speed gives **eight times** the power. A 2.5 m/s site is not 25% better "
    "than a 2.0 m/s site — it yields nearly double the power density.\n"
    "\n"
    "**The funnel effect:** mass conservation $Q = A\\,U$ means narrow, deep "
    "straits concentrate flow — that is why the Philippine inter-island channels "
    "(San Bernardino, Surigao) are hotspots."
, "subslide")

md(
    "## Turning a run into a resource map\n"
    "\n"
    "- Compute $P(t) = \\tfrac12\\rho\\,(u^2+v^2)^{3/2}$ every time step.\n"
    "- **Time-average** over a full spring\u2013neap cycle (15 days minimum) so we "
    "sample both springs and neaps.\n"
    "- Flag **hotspots** where $\\overline{P} \\ge 200$ W/m\u00b2.\n"
    "- Enforce the **CFL condition** $\\Delta t \\le \\Delta x / \\sqrt{g h}$ "
    "(auto-computed; lower `cfl_safety` if you see NaNs).\n"
    "\n"
    "Outputs are rasterised to a uniform grid (bilinear) for GIS compatibility — "
    "the four GeoTIFFs plus `results.nc` and `hotspots.geojson`."
, "subslide")

# --------------------------------------------------------------------------
# Demo B — run the solver live
# --------------------------------------------------------------------------
code(
    "import numpy as np\n"
    "import matplotlib.pyplot as plt\n"
    "\n"
    "# Prefer the real 'model' package; fall back to a tiny built-in solver.\n"
    "try:\n"
    "    from model.grid import StructuredGrid\n"
    "    from model.solver import ShallowWaterSolver\n"
    "    from model.forcing import make_synthetic_tidal_boundary\n"
    "    from model.utils import speed, power_density\n"
    "    HAVE_MODEL = True\n"
    "except Exception as exc:  # pragma: no cover\n"
    "    HAVE_MODEL = False\n"
    "    print('model package not importable:', exc, '-> built-in fallback')\n"
    "\n"
    "def build_grid(nx=60, ny=30, dx=1500.0, depth=60.0):\n"
    "    if HAVE_MODEL:\n"
    "        g = StructuredGrid.from_uniform(nx, ny, dx, dx)\n"
    "        g.h[:] = depth; g.h_u[:] = depth; g.h_v[:] = depth\n"
    "        g.open_boundary[:, 0] = True          # force the left column\n"
    "        return g\n"
    "    g = type('G', (), {})()\n"
    "    g.nx, g.ny, g.dx, g.dy = nx, ny, dx, dx\n"
    "    g.h = np.full((ny, nx), depth)\n"
    "    g.mask = np.ones((ny, nx), bool)\n"
    "    g.open_boundary = np.zeros((ny, nx), bool); g.open_boundary[:, 0] = True\n"
    "    return g\n"
    "\n"
    "def run_model(g, days=2.0, dt=20.0):\n"
    "    n = int(days*86400/dt)\n"
    "    if HAVE_MODEL:\n"
    "        bnd = make_synthetic_tidal_boundary(\n"
    "            int(g.open_boundary.sum()), amplitude=0.8, constituents=['M2', 'S2'])\n"
    "        solver = ShallowWaterSolver(g, cd=0.0025)\n"
    "        solver.set_open_boundary_eta(bnd)\n"
    "        probe = (g.ny//2, g.nx//2)\n"
    "        eta_ts = []; spd_ts = []; pd_ts = []\n"
    "        every = max(1, n//200)\n"
    "        def cb(s, step):\n"
    "            if step % every == 0:\n"
    "                eta_ts.append(s.eta[probe])\n"
    "                spd_ts.append(float(speed(s.u, s.v)[probe]))\n"
    "                pd_ts.append(float(power_density(s.u, s.v)[probe]))\n"
    "            return None\n"
    "        solver.run(dt, days*86400.0, callback=cb, progress_interval=1e9)\n"
    "        return np.array(eta_ts), np.array(spd_ts), np.array(pd_ts), solver\n"
    "    return _fallback_run(g, days, dt)\n"
    "\n"
    "def _fallback_run(g, days, dt):\n"
    "    ny, nx, dx, h = g.ny, g.nx, g.dx, g.h\n"
    "    eta = np.zeros((ny, nx)); u = np.zeros((ny, nx+1)); v = np.zeros((ny+1, nx))\n"
    "    Cd, g0, w = 0.0025, 9.81, 2*np.pi/(12.42*3600.0)\n"
    "    n = int(days*86400/dt); probe = (ny//2, nx//2)\n"
    "    eta_ts = []; spd_ts = []; pd_ts = []; every = max(1, n//200)\n"
    "    for k in range(n):\n"
    "        t = k*dt\n"
    "        eta[:, 0] = 0.8*np.cos(w*t)\n"
        "        dpx = (eta[:, 1:] - eta[:, :-1])/dx\n"
        "        sp = np.sqrt((u[:, 1:]**2 + u[:, :-1]**2)/2.0)   # speed at faces 0..nx-1\n"
        "        u[:, 1:-1] -= dt*(g0*dpx + Cd*sp[:, 1:]*u[:, 1:-1]/h[:, 1:])\n"
    "        dpy = (eta[1:, :] - eta[:-1, :])/dx\n"
    "        v[1:-1, :] -= dt*(g0*dpy)\n"
    "        fx = h*(u[:, 1:] - u[:, :-1]); fy = h*(v[1:, :] - v[:-1, :])\n"
    "        eta[1:-1, 1:-1] -= dt*(fx[1:-1, 1:-1]/dx + fy[1:-1, 1:-1]/dx)\n"
    "        if k % every == 0:\n"
    "            uc = (u[:, :-1] + u[:, 1:])/2.0; vc = (v[:-1, :] + v[1:, :])/2.0\n"
    "            s = np.sqrt(uc**2 + vc**2)\n"
    "            eta_ts.append(eta[probe]); spd_ts.append(s[probe])\n"
    "            pd_ts.append(0.5*1025*s[probe]**3)\n"
    "    return np.array(eta_ts), np.array(spd_ts), np.array(pd_ts), None\n"
    "\n"
    "g = build_grid()\n"
    "eta_ts, spd_ts, pd_ts, solver = run_model(g)\n"
    "print('solver :', 'repo model package' if HAVE_MODEL else 'built-in fallback')\n"
    "print(f'mean current speed : {spd_ts.mean():.3f} m/s')\n"
    "print(f'peak current speed : {spd_ts.max():.3f} m/s')\n"
    "print(f'mean power density : {pd_ts.mean():.1f} W/m^2')\n"
    "print(f'peak power density : {pd_ts.max():.1f} W/m^2')\n"
    "\n"
    "fig, ax = plt.subplots(1, 2, figsize=(11, 4))\n"
    "if solver is not None:\n"
    "    spd = speed(solver.u, solver.v)\n"
    "    im = ax[0].imshow(spd, origin='lower', cmap='viridis')\n"
    "    ax[0].set_title('Current speed |U| (m/s)'); plt.colorbar(im, ax=ax[0])\n"
    "else:\n"
    "    ax[0].plot(spd_ts); ax[0].set_title('Current speed at probe (m/s)')\n"
    "ax[1].plot(eta_ts, label='elevation eta (m)')\n"
    "ax[1].plot(spd_ts, label='speed |U| (m/s)')\n"
    "ax[1].set_title('Time series at probe'); ax[1].legend(); ax[1].set_xlabel('sample #')\n"
    "plt.tight_layout(); plt.show()"
)

# --------------------------------------------------------------------------
# 6. Web service
# --------------------------------------------------------------------------
md(
    "# 4 · Web Service\n"
    "\n"
    "Phase B serves the screening outputs through a **Flask REST API** backed by "
    "**MapLibre GL JS** for the interactive map.\n"
    "\n"
    "- Raster layers (GeoTIFF) are rendered to **colormapped PNG tiles** on the fly.\n"
    "- All endpoints are cache-friendly and read the same six output files.\n"
    "- Ships as a Docker image: `docker compose up -d --build` \u2192 "
    "**http://localhost:8001** (container 5000).\n"
    "\n"
    "| Endpoint | What it returns |\n"
    "|----------|-----------------|\n"
    "| `/api/layers` | Metadata for every layer (bounds, stats, legend) |\n"
    "| `/api/tiles/{layer}/{z}/{x}/{y}.png` | Colormapped raster tiles |\n"
    "| `/api/query?lat=&lon=&layer=` | Value at a point |\n"
    "| `/api/timeseries?lat=&lon=` | Tidal curve from `results.nc` |\n"
    "| `/api/hotspots?min=&limit=` | Ranked hotspots (GeoJSON) |\n"
    "| `/api/area_stats` | POST polygon \u2192 resource stats |\n"
    "| `/api/resource` | Filtered-domain totals (area / MW / AEP) |\n"
    "| `/api/turbines` · `/api/turbine_performance` | Turbine specs & yield |\n"
    "| `/api/download/{file}` | GeoTIFF / GeoJSON / NetCDF download |\n"
)

md(
    "## The map — the screening layers\n"
    "\n"
    "The interactive map renders each canonical GeoTIFF as a switchable overlay. "
    "The screenshots below were captured from a run served over the TELEMAC-2D "
    "region outputs (generated in `output/screenshots/`):\n"
    "\n"
    "![Overview](../../output/screenshots/01_overview.png)\n"
    "\n"
    "*Overview, then the mean power density, max current speed, bathymetry, and "
    "distance-to-coast layers.*\n"
    "\n"
    "![Power](../../output/screenshots/02_power.png)\n"
    "![Speed](../../output/screenshots/03_speed.png)\n"
    "![Depth](../../output/screenshots/04_depth.png)\n"
    "![Distance](../../output/screenshots/05_distance.png)"
, "subslide")

# --------------------------------------------------------------------------
# Demo C — query the live API
# --------------------------------------------------------------------------
code(
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
    "    print('Resource (>=200 W/m^2):')\n"
    "    for k in ('n_cells', 'area_km2', 'mean_power_density',\n"
    "              'extractable_mw', 'aep_gwh_yr'):\n"
    "        print(f'  {k:22s}: {res.get(k)}')\n"
    "except Exception as exc:\n"
    "    print('Web service not running on', BASE, '->', exc)\n"
    "    print('Start it with:  docker compose up -d --build')\n"
    "    print('Then open http://localhost:8001')\n"
    "    print('Sample /api/resource response:')\n"
    "    print(json.dumps({\n"
    "        'n_cells': 1559, 'area_km2': 6120.4,\n"
    "        'mean_power_density': 412.7, 'extractable_mw': 2526.9,\n"
    "        'aep_gwh_yr': 22136.1}, indent=2))"
)

# --------------------------------------------------------------------------
# 7. Features
# --------------------------------------------------------------------------
md(
    "# 5 · Features\n"
    "\n"
    "The MSP tool is more than a map viewer — it supports real site-screening "
    "workflows:\n"
    "\n"
    "- **Site inspector** — click anywhere for point stats, a tidal curve, and "
    "turbine yield.\n"
    "- **Ranked hotspots** — sortable list of the best sites.\n"
    "- **Export** — download GeoTIFF / GeoJSON / NetCDF.\n"
    "- **Polygon assessment** — draw a site, get area, MW and AEP.\n"
    "- **Resource screening** — filter by power & depth \u2192 national totals.\n"
    "- **Measure tool** — distance between points.\n"
    "- **Turbine performance** — top-10 real turbines, capacity factor & AEP."
)

md(
    "## TELEMAC-2D refinement regions\n"
    "\n"
    "The same map UI serves the high-resolution TELEMAC-2D refinements for the "
    "top three hotspot regions (`output/telemac/region-00X/`), rendered with the "
    "canonical layers:\n"
    "\n"
    "![Region 001](../../output/screenshots/06_telemac_region-001.png)\n"
    "![Region 002](../../output/screenshots/07_telemac_region-002.png)\n"
    "![Region 003](../../output/screenshots/08_telemac_region-003.png)"
, "subslide")

# --------------------------------------------------------------------------
# Demo D — turbine performance
# --------------------------------------------------------------------------
code(
    "import numpy as np\n"
    "import matplotlib.pyplot as plt\n"
    "\n"
    "try:\n"
    "    from web.turbines import all_turbine_specs, performance\n"
    "    HAVE_TURB = True\n"
    "except Exception as exc:\n"
    "    HAVE_TURB = False\n"
    "    print('web.turbines not importable:', exc, '-> inline model')\n"
    "\n"
    "def power_curve_kw(rated_kw, cut_in, cut_out, u_rated, u):\n"
    "    if u < cut_in or u >= cut_out:\n"
    "        return 0.0\n"
    "    if u >= u_rated:\n"
    "        return rated_kw\n"
    "    frac = (u - cut_in) / (u_rated - cut_in)\n"
    "    return rated_kw * frac**3\n"
    "\n"
    "if HAVE_TURB:\n"
    "    specs = all_turbine_specs()\n"
    "    top = specs[0]\n"
    "    print('Top turbine:', top['name'], f\"({top['manufacturer']})\")\n"
    "    print(f\"  rated power : {top['rated_power_kw']} kW\")\n"
    "    print(f\"  rated speed : {top['rated_speed_mps']} m/s\")\n"
    "    us = np.linspace(0, top['cut_out_mps'] + 0.3, 200)\n"
    "    p = [power_curve_kw(top['rated_power_kw'], top['cut_in_mps'],\n"
    "                        top['cut_out_mps'], top['rated_speed_mps'], uu) for uu in us]\n"
    "    plt.figure(figsize=(7, 4))\n"
    "    plt.plot(us, p, lw=2)\n"
    "    for x, lab in [(top['cut_in_mps'], 'cut-in'),\n"
    "                   (top['rated_speed_mps'], 'rated'),\n"
    "                   (top['cut_out_mps'], 'cut-out')]:\n"
    "        plt.axvline(x, ls=':', label=lab)\n"
    "    plt.xlabel('Current speed U (m/s)'); plt.ylabel('Power (kW)')\n"
    "    plt.title(f\"{top['name']} power curve\"); plt.legend(); plt.show()\n"
    "    if 'spd_ts' in globals():           # reuse the Demo-B speed series\n"
    "        t_hours = list(np.linspace(0, 2*24, len(spd_ts)))\n"
    "        perf = performance(top, list(spd_ts), t_hours)\n"
    "        print(f\"  capacity factor : {perf['capacity_factor']*100:.1f} %\")\n"
    "        print(f\"  AEP             : {perf['aep_gwh_yr']:.3f} GWh/yr\")\n"
    "        print(f\"  % time at rated : {perf['pct_time_at_rated']:.1f} %\")\n"
    "else:\n"
    "    rated, cin, cout, urated = 2000.0, 0.7, 4.0, 2.2\n"
    "    us = np.linspace(0, cout + 0.3, 200)\n"
    "    p = [power_curve_kw(rated, cin, cout, urated, uu) for uu in us]\n"
    "    plt.figure(figsize=(7, 4)); plt.plot(us, p, lw=2)\n"
    "    plt.xlabel('Current speed U (m/s)'); plt.ylabel('Power (kW)')\n"
    "    plt.title('Example turbine power curve (inline)'); plt.show()"
)

# --------------------------------------------------------------------------
# 8. Closing
# --------------------------------------------------------------------------
md(
    "# Wrap-up & Quick Start\n"
    "\n"
    "**Run the whole stack locally:**\n"
    "```bash\n"
    "docker compose up -d --build     # web map at http://localhost:8001\n"
    "python -m src.model.run          # (optional) regenerate outputs\n"
    "```\n"
    "\n"
    "**Try the live demos in this notebook:**\n"
    "- Demo A — visualise the power-density field.\n"
    "- Demo B — run the shallow-water solver (real `model` pkg or fallback).\n"
    "- Demo C — query the Flask API.\n"
    "- Demo D — plot a turbine power curve & yield.\n"
    "\n"
    "**Docs:** `docs/README.md`, `docs/concepts/MODEL.md`, "
    "`docs/architecture/WORKFLOW.md`, `docs/engines/TELEMAC.md`, "
    "`docs/notebooks/EXPLAINER.ipynb`.\n"
    "\n"
    "MIT licensed · contributions welcome."
)

# --------------------------------------------------------------------------
notebook = {
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

OUT.parent.mkdir(parents=True, exist_ok=True)
with OUT.open("w", encoding="utf-8") as f:
    json.dump(notebook, f, indent=1, ensure_ascii=False)

print(f"wrote {OUT} with {len(cells)} cells")
