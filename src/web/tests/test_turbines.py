"""Tests for the tidal-turbine dataset, power-curve model, and API endpoints."""

from __future__ import annotations

import numpy as np
import pytest

import web.app as web_app
from web.turbines import (
    TURBINES,
    all_performance,
    all_turbine_specs,
    performance,
    power_curve_points,
    power_kw,
    rated_speed_mps,
)

# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------


def test_top10_dataset():
    assert len(TURBINES) == 10
    # sorted by rated power descending
    powers = [t["rated_power_kw"] for t in TURBINES]
    assert powers == sorted(powers, reverse=True)
    # unique ids
    ids = [t["id"] for t in TURBINES]
    assert len(set(ids)) == len(ids)


def test_specs_are_physically_sensible():
    for t in all_turbine_specs():
        assert t["rated_power_kw"] > 0
        assert t["rotor_diameter_m"] > 0
        assert t["swept_area_m2"] > 0
        assert 0 < t["cut_in_mps"] < t["rated_speed_mps"] < t["cut_out_mps"]
        assert len(t["power_curve"]) > 10


def test_rated_speed_reaches_rated_power():
    for t in TURBINES:
        u_rated = rated_speed_mps(t)
        assert abs(power_kw(t, u_rated) - t["rated_power_kw"]) < 1e-6


def test_power_curve_behaviour():
    for t in TURBINES:
        # zero below cut-in and at/above cut-out
        assert power_kw(t, t["cut_in_mps"] - 0.05) == 0.0
        assert power_kw(t, t["cut_out_mps"]) == 0.0
        # monotonic non-decreasing up to cut-out, then hard shutdown to 0
        pts = power_curve_points(t)
        p = [pt[1] for pt in pts]
        u = [pt[0] for pt in pts]
        before_cutout = [
            pp for uu, pp in zip(u, p, strict=False) if uu < t["cut_out_mps"]
        ]
        for a, b in zip(before_cutout, before_cutout[1:], strict=False):
            assert a <= b + 1e-9, f"power curve not monotonic for {t['id']}"
        # peaks exactly at rated power
        assert max(before_cutout) == pytest.approx(t["rated_power_kw"], rel=1e-3)
        # cut-out shuts the turbine down
        assert p[-1] == 0.0


def test_performance_metrics():
    t = TURBINES[0]
    speed = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5]
    hours = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    p = performance(t, speed, hours)
    assert p["energy_window_kwh"] > 0
    assert 0 <= p["capacity_factor"] <= 1
    assert p["aep_gwh_yr"] == pytest.approx(
        p["capacity_factor"] * t["rated_power_kw"] * 8760 / 1e6, rel=1e-2
    )
    assert p["pct_time_generating"] > 0
    # no flow → no energy
    p0 = performance(t, [0.1] * 7, hours)
    assert p0["energy_window_kwh"] == 0.0
    assert p0["capacity_factor"] == 0.0


def test_all_performance_returns_10():
    t = np.linspace(0, 24, 49)
    u = 1.5 + np.cos(2 * np.pi * t / 12.42)
    res = all_performance(list(u), list(t))
    assert len(res) == 10
    assert all(0 <= r["capacity_factor"] <= 1 for r in res)


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------


def test_turbines_endpoint(client):
    resp = client.get("/api/turbines")
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data["turbines"]) == 10
    t = data["turbines"][0]
    for key in (
        "id",
        "name",
        "manufacturer",
        "rated_power_kw",
        "rotor_diameter_m",
        "cut_in_mps",
        "cut_out_mps",
        "rated_speed_mps",
        "power_curve",
    ):
        assert key in t


def test_turbine_performance_endpoint(client):
    resp = client.get("/api/turbine_performance?lat=11.5&lon=121.0")
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data["turbines"]) == 10
    assert data["window_hours"] > 0
    assert data["site_summary"]["n_points"] >= 1
    kairyu = next(t for t in data["turbines"] if t["id"] == "kairyu")
    assert len(kairyu["power_series_kw"]) == data["site_summary"]["n_points"]
    assert 0 <= kairyu["capacity_factor"] <= 1


def test_turbine_performance_requires_params(client):
    assert client.get("/api/turbine_performance").status_code == 400


def test_turbine_performance_missing(tmp_path):
    web_app.GEOTIFF_PATH = str(tmp_path / "nope.tif")
    web_app.app.config.update(TESTING=True)
    with web_app.app.test_client() as c:
        assert c.get("/api/turbine_performance?lat=11&lon=121").status_code == 404
