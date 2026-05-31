# Philippine Tidal Current Energy — Initial Screening Plan

## 1. Project Overview

A simple 2D depth-averaged hydrodynamic model in Python to perform an initial assessment of tidal-current energy potential — identifying promising zones for in-stream device deployment before committing to a full TELEMAC-2D simulation.

- **Primary output:** GeoTIFF of mean tidal-current power density (W/m²)
- **Model type:** 2D shallow-water equations, finite-difference, structured Arakawa C-grid
- **Implementation:** Pure Python + NumPy (Numba/GPU optional for larger domains)
- **Bathymetry:** GEBCO 2024 (15 arc-second, regridded to ~1–2 km)
- **Land boundary:** GADM Philippines shapefile or OSM coastline
- **Tidal forcing:** FES2014 / TPXO9 harmonic constituents at open boundaries
- **Web visualisation:** Lightweight (Folium / Leaflet) or full MapLibre + GeoServer stack

---

## 2. Governing Equations

The model solves the depth-averaged shallow-water equations on a rotating sphere (f-plane or β-plane approximation).

### 2.1 Continuity

$$
\frac{\partial \eta}{\partial t} + \frac{\partial (h u)}{\partial x} + \frac{\partial (h v)}{\partial y} = 0
$$

### 2.2 Momentum

$$
\frac{\partial u}{\partial t} + u\frac{\partial u}{\partial x} + v\frac{\partial u}{\partial y} - f v =
-g \frac{\partial \eta}{\partial x} - \frac{\tau_{b,x}}{\rho \, h} + A_h \nabla^2 u
$$

$$
\frac{\partial v}{\partial t} + u\frac{\partial v}{\partial x} + v\frac{\partial v}{\partial y} + f u =
-g \frac{\partial \eta}{\partial y} - \frac{\tau_{b,y}}{\rho \, h} + A_h \nabla^2 v
$$

| Symbol | Name | Units | Typical value |
|--------|------|-------|---------------|
| η | Free-surface elevation | m | — |
| h | Total water depth (bathymetry + η) | m | — |
| u, v | Depth-averaged velocity (x, y) | m/s | — |
| f | Coriolis parameter | 1/s | 2Ω sin(lat) |
| g | Gravitational acceleration | m/s² | 9.81 |
| ρ | Seawater density | kg/m³ | 1025 |
| τ_b | Bottom shear stress | N/m² | ρ C_d ‖u‖ u / h² |
| C_d | Bottom drag coefficient | — | 0.0025 |
| A_h | Horizontal eddy viscosity | m²/s | 1–10 |

### 2.3 Bottom Friction

$$
\tau_{b,x} = \rho \cdot C_d \cdot \frac{u \sqrt{u^2 + v^2}}{h^2}
\qquad
\tau_{b,y} = \rho \cdot C_d \cdot \frac{v \sqrt{u^2 + v^2}}{h^2}
$$

### 2.4 Tidal-Current Power Density

$$
P \;=\; \frac{1}{2} \, \rho \, U^3
\qquad\text{where}\qquad
U = \sqrt{u^2 + v^2}
$$

Time-averaged over the simulation period (≥ 15 days to capture one spring–neap cycle) and rasterised to a GeoTIFF.

---

## 3. Numerical Method

### 3.1 Spatial Discretisation — Arakawa C-Grid

```
    ┌─────── v[i,j+1] ───────┐
    │                        │
  u[i,j]   η[i,j]   u[i+1,j] │
    │                        │
    └─────── v[i,j] ─────────┘
```

- **η** at cell centres (i, j)
- **u** at east–west faces (i, j)
- **v** at north–south faces (i, j)
- **h** interpolated to velocity points
- Semi-implicit treatment of the Coriolis term to avoid instability

### 3.2 Time Integration

- **External mode (barotropic):** Split-explicit with a short time step Δt_e, satisfying the CFL condition for surface gravity waves.
- **Internal / advective terms:** Updated every macro time step Δt_m = N_split · Δt_e using Adams-Bashforth 3 (AB3) or a low-storage Runge-Kutta (RK4).
- **Bottom friction:** Treated semi-implicitly to prevent limit-cycle oscillations in shallow cells.

### 3.3 Wetting & Drying

Cells with total depth h < h_min (e.g., 0.1 m) are masked as dry and excluded from the momentum solve. Wetting occurs when the free surface from a neighbouring wet cell exceeds the local bed elevation.

### 3.4 Boundary Conditions

| Boundary type | Condition |
|---------------|-----------|
| Open (liquid) | Prescribed η(t) from tidal harmonics (M2, S2, K1, O1 minimum) |
| Closed (solid) | u_n = 0, ∂η/∂n = 0 (free-slip or no-slip) |
| Land mask | Zero velocity, no normal flow |

Tidal elevation at each open-boundary cell is reconstructed as:

$$
\eta(t) = \sum_{k} A_k \cos(\omega_k t + \phi_k)
$$

where A_k, ϕ_k are the amplitude and phase of constituent k interpolated from FES2014 / TPXO9 at the boundary node.

---

## 4. Python Implementation

### 4.1 Module Layout

```
model/
├── __init__.py
├── grid.py          # StructuredGrid class (mask, metrics, coordinates)
├── bathymetry.py    # Load & regrid GEBCO, set land mask
├── forcing.py       # Tidal BC from FES2014/TPXO NetCDF
├── solver.py        # ShallowWaterSolver class (C-grid, AB3/RK4, wet-dry)
├── output.py        # NetCDF writer, power-density rasterizer
├── utils.py         # CFL, Coriolis, interpolation helpers
├── config.yaml      # Simulation parameters
├── run.py           # Main entry point
└── tests/
    ├── test_standing_wave.py   # Analytical test (sloshing seiche)
    ├── test_tidal_channel.py   # 1D channel with prescribed tide
    └── test_conservation.py    # Mass / energy conservation checks
```

### 4.2 Dependencies

```
numpy>=1.24
scipy>=1.10
xarray>=2023
rioxarray>=0.14
pyproj>=3.5
pyyaml>=6.0
numba>=0.57          # optional — 5–10× speedup for inner loops
matplotlib>=3.7      # debug plots
pytest>=7.4          # tests
```

### 4.3 Key Classes

#### `StructuredGrid` (`grid.py`)

```python
@dataclass
class StructuredGrid:
    lon  : np.ndarray   # (nx,)   cell-centre longitudes
    lat  : np.ndarray   # (ny,)   cell-centre latitudes
    x    : np.ndarray   # (nx,)   projected x [m]
    y    : np.ndarray   # (ny,)   projected y [m]
    dx   : float        # uniform grid spacing in x [m]
    dy   : float        # uniform grid spacing in y [m]
    mask : np.ndarray   # (ny, nx) 1=wet, 0=land
    h    : np.ndarray   # (ny, nx) bathymetric depth [m], positive down
    f    : np.ndarray   # (ny, nx) Coriolis parameter [1/s]
```

#### `ShallowWaterSolver` (`solver.py`)

```python
class ShallowWaterSolver:
    def __init__(self, grid: StructuredGrid, config: dict): ...
    def set_initial_conditions(self, eta0=None, u0=0, v0=0): ...
    def step(self, dt: float, eta_bc: np.ndarray, forcing_wind=None): ...
    def run(self, start_time, end_time, dt, bc_generator): ...
    def power_density(self) -> np.ndarray: ...  # time-mean P [W/m²]
```

### 4.4 Configuration (`config.yaml`)

```yaml
domain:
  lon_min: 116.0
  lon_max: 130.0
  lat_min: 4.0
  lat_max: 22.0
  resolution_km: 2.0           # target grid spacing

bathymetry:
  source: gebco
  path: data/GEBCO_2024.nc
  min_depth: 2.0               # enforce minimum depth [m]
  max_depth: 6000.0            # clip unrealistic depths

simulation:
  start_time: "2024-01-01T00:00:00"
  duration_days: 15            # ≥ 1 spring-neap cycle
  dt_external: 10.0            # barotropic time step [s]
  n_split: 10                  # macro/micro split ratio
  cd: 0.0025                   # bottom drag coefficient
  ah: 5.0                      # horizontal eddy viscosity
  rho: 1025.0                  # seawater density

tidal_forcing:
  source: fes2014              # or tpxo9
  path: data/fes2014/
  constituents: [M2, S2, K1, O1]  # minimum set

output:
  dir: output/
  save_interval_hours: 1
  fields: [eta, u, v, power_density]
  final_geotiff: tidal_power_density.tif
```

---

## 5. Data Preparation

### 5.1 Bathymetry

| Step | Tool | Command / Description |
|------|------|-----------------------|
| Download | GEBCO | [GEBCO 2024 NetCDF](https://www.gebco.net/data_and_products/gridded_bathymetry_data/gebco_2024/) |
| Clip to AOI | `gdal_translate` | `gdal_translate -projwin 116 22 130 4 NETCDF:GEBCO_2024.nc:elevation data/gebco_aoi.nc` |
| Regrid | `xarray` | Coarsen to target resolution with conservative or bilinear interpolation |

### 5.2 Land Mask

| Step | Tool | Description |
|------|------|-------------|
| Download | GADM / Geofabrik | Philippines boundary shapefile |
| Rasterise | `gdal_rasterize` or `rasterio` | Burn land=0, water=1 onto the model grid |
| Combine | Python | `mask = (rasterized_land == 1) & (depth >= min_depth)` |

### 5.3 Tidal Boundary Conditions

| Step | Tool | Description |
|------|------|-------------|
| Download | AVISO (FES2014) or TPXO | NetCDF of amplitude + phase for M2, S2, K1, O1 |
| Interpolate | `scipy.interpolate` | Extract A_k, ϕ_k at each open-boundary grid cell |
| Write BC file | `xarray` → NetCDF | `tidal_bc.nc` with dims (time, n_boundary_cells) |

---

## 6. Verification & Validation

### 6.1 Analytical Test Cases

| Test | Description | Checks |
|------|-------------|--------|
| Standing wave (seiche) | Closed rectangular basin, initial surface gradient | Wave period matches Merian's formula |
| Tidal channel flow | 1D channel forced by M2 only, constant depth | Velocity amplitude vs. analytical solution |
| Kelvin wave | Rotating channel with coastal boundary | Phase propagation, cross-shore structure |
| Mass conservation | Closed basin, zero net input | Total volume change < 1e-6 relative |

### 6.2 Real-World Validation

- Compare η(t) at coastal points with tide-gauge data (NAMRIA, IOC sea-level stations)
- Cross-check hotspot locations against known tidal-energy straits:
  - San Bernardino Strait (~12.5°N, 124.1°E)
  - Surigao Strait (~10.0°N, 125.3°E)
  - Basilan Strait (~6.8°N, 122.0°E)
- Compare depth-averaged current magnitudes with published ADCP data where available

---

## 7. Post-Processing & Output

### 7.1 Workflow

```
 SELAFIN-like           time-mean               GeoTIFF
 or NetCDF output  ──▶  power density  ──▶  tidal_power_density.tif
 (u, v, η, t)          per cell                (EPSG:4326, float32)
```

### 7.2 Key Outputs

| Product | Format | Description |
|---------|--------|-------------|
| `results.nc` | NetCDF | Full 3D time series (t, y, x) of η, u, v |
| `power_density.nc` | NetCDF | Time-mean and P95 power density |
| `tidal_power_density.tif` | Cloud-Optimised GeoTIFF | Rasterised power density, EPSG:4326 |
| `hotspots.geojson` | GeoJSON | Cells exceeding threshold (e.g., P_mean > 200 W/m²) |

### 7.3 Classification Thresholds

| Category | P_mean (W/m²) | Suitability |
|----------|---------------|-------------|
| Low | < 50 | Not viable |
| Marginal | 50–200 | Possible with future technology |
| Moderate | 200–500 | Suitable for array deployment |
| High | 500–1000 | Prime candidate |
| Excellent | > 1000 | Highest priority |

---

## 8. Web Visualisation

### 8.1 Lightweight Option (Initial Screening)

Use **Folium** + **Leaflet** for quick interactive viewing with zero infrastructure:

```python
import folium
import rioxarray

m = folium.Map(location=[12.5, 122], zoom_start=6)
folium.raster_layers.ImageOverlay(
    image="output/tidal_power_density.tif",
    bounds=[[4, 116], [22, 130]],
    colormap=..., opacity=0.7
).add_to(m)
m.save("map.html")
```

### 8.2 Full Stack Option (Production)

| Component | Technology | Purpose |
|-----------|------------|---------|
| Map tiles | GeoServer (COG plugin) | Serve styled WMS/WMTS from GeoTIFF |
| API | Flask | `/api/query?lat=&lon=`, `/api/download` |
| Frontend | MapLibre GL JS | Interactive map with overlay, legend, click-to-query |
| Deployment | Docker Compose | Single-command stack launch |

---

## 9. Implementation Phases

| Phase | Duration | Deliverables |
|-------|----------|-------------|
| 1. Data acquisition | 0.5 week | Clipped & regridded bathymetry, land mask, tidal BC NetCDF |
| 2. Grid & solver core | 1–1.5 weeks | `model/` package with passing analytical tests |
| 3. Philippine simulation | 1 week | Production run, validated time series |
| 4. Post-processing | 0.5 week | Power-density GeoTIFF, hotspot GeoJSON |
| 5. Visualisation | 0.5 week | Folium map or full web stack |
| 6. Documentation | 0.5 week | README, methodology, input data guide |

**Total estimated time: 4–5 weeks** (one person, part-time).

---

## 10. Next Steps After Screening

This initial Python model identifies high-potential zones. Promising sites then graduate to:

1. **High-resolution unstructured mesh** (via TELEMAC-2D) for detailed resource characterisation
2. **Turbine-array modelling** (actuator disk or momentum-sink parameterisations)
3. **Environmental impact assessment** (sediment transport, far-field effects)
4. **Economic analysis** (capacity factor, LCOE, grid-connection cost)

---

## 11. Software Requirements

| Tool | Version | Purpose |
|------|---------|---------|
| Python | ≥ 3.10 | Core language |
| NumPy | ≥ 1.24 | Array operations |
| SciPy | ≥ 1.10 | Interpolation, sparse solvers |
| xarray / rioxarray | ≥ 2023 | NetCDF/GeoTIFF I/O |
| GDAL | ≥ 3.8 | Raster processing |
| Numba | ≥ 0.57 | Optional JIT acceleration |
| pytest | ≥ 7.4 | Unit / integration tests |
| Folium | ≥ 0.15 | Quick interactive map |
| Docker | ≥ 24 | Web stack containerisation (Phase B) |
