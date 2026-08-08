"""Tidal in-stream turbine dataset and performance model.

A curated sample of the top-10 most notable tidal in-stream turbines in the
world (by rated power / deployment).  Specifications are approximate
published figures; the *rated speed* is derived from each turbine's rated
power, swept area and a typical power coefficient so the power-curve model
is physically self-consistent:

    P(U) = 0                                          U < cut-in
    P(U) = P_rated · ((U − cut-in)/(U_rated − cut-in))³   cut-in ≤ U < U_rated
    P(U) = P_rated                                    U_rated ≤ U < cut-out
    P(U) = 0                                          U ≥ cut-out

The cubic ramp mimics the U³ behaviour of the kinetic power flux while
guaranteeing P → P_rated at the rated speed.
"""

from __future__ import annotations

import math

import numpy as np

RHO_SEAWATER = 1025.0  # kg/m³
CP = 0.42  # typical tidal-turbine power coefficient at rated conditions

# id: stable key used by the API / frontend.
# rotor_diameter_m: per-rotor diameter; n_rotors: 1 (single) or 2 (twin).
TURBINES: list[dict] = [
    {
        "id": "kairyu",
        "name": "Kairyu",
        "manufacturer": "Kawasaki Heavy Industries",
        "country": "Japan",
        "project": "Naruto Strait demo",
        "rated_power_kw": 3000.0,
        "rotor_diameter_m": 20.0,
        "n_rotors": 2,
        "cut_in_mps": 0.6,
        "cut_out_mps": 4.5,
    },
    {
        "id": "orbital-o2",
        "name": "O2",
        "manufacturer": "Orbital Marine Power",
        "country": "United Kingdom",
        "project": "EMEC, Orkney",
        "rated_power_kw": 2000.0,
        "rotor_diameter_m": 20.0,
        "n_rotors": 2,
        "cut_in_mps": 0.7,
        "cut_out_mps": 4.0,
    },
    {
        "id": "atlantis-ar2000",
        "name": "AR2000",
        "manufacturer": "SIMEC Atlantis Energy",
        "country": "United Kingdom",
        "project": "MeyGen (planned class)",
        "rated_power_kw": 2000.0,
        "rotor_diameter_m": 20.0,
        "n_rotors": 1,
        "cut_in_mps": 0.5,
        "cut_out_mps": 4.0,
    },
    {
        "id": "magallanes-ATIR",
        "name": "ATIR",
        "manufacturer": "Magallanes Renovables",
        "country": "Spain",
        "project": "EMEC (floating)",
        "rated_power_kw": 1500.0,
        "rotor_diameter_m": 20.0,
        "n_rotors": 1,
        "cut_in_mps": 0.7,
        "cut_out_mps": 4.5,
    },
    {
        "id": "atlantis-ar1500",
        "name": "AR1500",
        "manufacturer": "SIMEC Atlantis Energy",
        "country": "United Kingdom",
        "project": "MeyGen, Pentland Firth",
        "rated_power_kw": 1500.0,
        "rotor_diameter_m": 18.0,
        "n_rotors": 1,
        "cut_in_mps": 0.5,
        "cut_out_mps": 4.0,
    },
    {
        "id": "andritz-hs1000",
        "name": "HS1000",
        "manufacturer": "Andritz Hydro Hammerfest",
        "country": "Austria / Norway",
        "project": "EMEC, Orkney",
        "rated_power_kw": 1000.0,
        "rotor_diameter_m": 18.0,
        "n_rotors": 1,
        "cut_in_mps": 0.7,
        "cut_out_mps": 4.0,
    },
    {
        "id": "hydroquest-oceanquest",
        "name": "OceanQuest",
        "manufacturer": "HydroQuest",
        "country": "France",
        "project": "Paimpol-Bréhat",
        "rated_power_kw": 1000.0,
        "rotor_diameter_m": 10.0,
        "n_rotors": 2,
        "cut_in_mps": 0.7,
        "cut_out_mps": 4.0,
    },
    {
        "id": "sabella-d10",
        "name": "D10",
        "manufacturer": "Sabella",
        "country": "France",
        "project": "Fromveur, Ushant",
        "rated_power_kw": 1000.0,
        "rotor_diameter_m": 10.0,
        "n_rotors": 1,
        "cut_in_mps": 0.8,
        "cut_out_mps": 4.5,
    },
    {
        "id": "tocardo-t2",
        "name": "T2",
        "manufacturer": "Tocardo",
        "country": "Netherlands",
        "project": "Den Helder / Eastern Scheldt",
        "rated_power_kw": 250.0,
        "rotor_diameter_m": 10.0,
        "n_rotors": 1,
        "cut_in_mps": 0.6,
        "cut_out_mps": 3.5,
    },
    {
        "id": "nova-m100",
        "name": "M100",
        "manufacturer": "Nova Innovation",
        "country": "United Kingdom",
        "project": "Shetland Tidal Array",
        "rated_power_kw": 100.0,
        "rotor_diameter_m": 10.0,
        "n_rotors": 1,
        "cut_in_mps": 0.7,
        "cut_out_mps": 3.5,
    },
]

# Sort by rated power descending — the "top 10" list.
TURBINES = sorted(TURBINES, key=lambda t: t["rated_power_kw"], reverse=True)


def swept_area_m2(turbine: dict) -> float:
    """Total swept area of a turbine's rotor(s) [m²]."""
    r = turbine["rotor_diameter_m"] / 2.0
    return turbine["n_rotors"] * math.pi * r * r


def rated_speed_mps(turbine: dict) -> float:
    """Rated current speed [m/s] for which P_rated = ½ρACp·U³."""
    p_w = turbine["rated_power_kw"] * 1000.0
    denom = 0.5 * RHO_SEAWATER * swept_area_m2(turbine) * CP
    return (p_w / denom) ** (1.0 / 3.0)


def turbine_specs(turbine: dict) -> dict:
    """Public metadata for one turbine (with derived rated speed)."""
    base = dict(turbine)
    base["swept_area_m2"] = round(swept_area_m2(turbine), 1)
    base["rated_speed_mps"] = round(rated_speed_mps(turbine), 2)
    base["power_curve"] = power_curve_points(turbine)
    return base


def all_turbine_specs() -> list[dict]:
    return [turbine_specs(t) for t in TURBINES]


def power_kw(turbine: dict, speed_mps: float) -> float:
    """Instantaneous turbine electrical output [kW] at a given current speed."""
    cut_in = turbine["cut_in_mps"]
    cut_out = turbine["cut_out_mps"]
    p_rated = turbine["rated_power_kw"]
    if speed_mps < cut_in or speed_mps >= cut_out:
        return 0.0
    u_rated = rated_speed_mps(turbine)
    if speed_mps >= u_rated:
        return p_rated
    frac = (speed_mps - cut_in) / (u_rated - cut_in)
    return p_rated * frac**3


def power_curve_points(
    turbine: dict, step: float = 0.05, pad: float = 0.5
) -> list[list[float]]:
    """Power-curve samples [[U, P_kW], ...] from 0 to cut-out + *pad*."""
    u_max = turbine["cut_out_mps"] + pad
    u = np.arange(0.0, u_max, step)
    return [[round(float(s), 3), round(power_kw(turbine, float(s)), 2)] for s in u]


def performance(turbine: dict, speed_ts: list[float], time_hours: list[float]) -> dict:
    """Simulate one turbine over a speed time series.

    Parameters
    ----------
    turbine : dict
    speed_ts : list[float]
        Depth-averaged current speed at each sample [m/s].
    time_hours : list[float]
        Sample times [hours since simulation start].

    Returns
    -------
    dict
        Energy, capacity factor, AEP, etc. over the simulation window.
    """
    p_rated = turbine["rated_power_kw"]
    p_ts = np.array([power_kw(turbine, float(u)) for u in speed_ts], dtype=np.float64)

    window_h = float(time_hours[-1] - time_hours[0]) if len(time_hours) >= 2 else 1.0

    # Trapezoidal integration of power over the window
    if len(p_ts) >= 2 and window_h > 0:
        energy_kwh = float(
            np.trapezoid(p_ts, x=np.asarray(time_hours, dtype=np.float64))
        )
        mean_kw = energy_kwh / window_h
    else:
        energy_kwh = 0.0
        mean_kw = 0.0

    cf = min(mean_kw / p_rated, 1.0) if p_rated > 0 else 0.0
    aep_gwh_yr = cf * p_rated * 8760.0 / 1e6

    return {
        "id": turbine["id"],
        "energy_window_kwh": round(energy_kwh, 1),
        "mean_output_kw": round(mean_kw, 2),
        "capacity_factor": round(cf, 4),
        "aep_gwh_yr": round(aep_gwh_yr, 3),
        "pct_time_generating": round(
            100.0 * float(np.mean(p_ts > 0.0)) if len(p_ts) else 0.0, 1
        ),
        "pct_time_at_rated": round(
            100.0 * float(np.mean(p_ts >= p_rated)) if len(p_ts) else 0.0, 1
        ),
        "max_output_kw": round(float(np.max(p_ts)) if len(p_ts) else 0.0, 2),
        "power_series_kw": [round(float(x), 2) for x in p_ts],
    }


def all_performance(speed_ts: list[float], time_hours: list[float]) -> list[dict]:
    """Performance of every turbine over one site's speed time series."""
    return [performance(t, speed_ts, time_hours) for t in TURBINES]
