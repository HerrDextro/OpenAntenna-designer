import math

import numpy as np
import pytest

from antennasim.analysis.coil import design_coil, wheeler_inductance_uh
from antennasim.analysis.feedline import apply_feed_system, transform_through_line
from antennasim.analysis.ground_loss import estimate_ground_loss
from antennasim.analysis.swr import bandwidth, resonances, swr
from antennasim.analysis.tuner import find_root
from antennasim.model.materials import COAX


def test_swr_basic():
    assert swr(50, 50) == pytest.approx(1.0)
    assert swr(100, 50) == pytest.approx(2.0)
    assert swr(25, 50) == pytest.approx(2.0)


def test_resonance_interpolation():
    f = np.array([13.0, 14.0, 15.0])
    z = np.array([30 - 20j, 35 + 0j + 10j, 40 + 40j])
    assert resonances(f, z) == pytest.approx([13.0 + 20 / 30])


def test_bandwidth_edges():
    f = np.linspace(13, 15, 5)  # 13, 13.5, 14, 14.5, 15
    s = np.array([3.0, 1.5, 1.1, 1.5, 3.0])
    lo, hi = bandwidth(f, s, 2.0)
    assert lo == pytest.approx(13.5 - 0.5 / 3)
    assert hi == pytest.approx(14.5 + 0.5 / 3)
    assert bandwidth(f, s + 5, 2.0) is None


def test_lossless_line_quarter_and_half_wave():
    z0, zl, beta = 50.0, 100.0 + 0j, 2 * math.pi / 10.0
    quarter = transform_through_line(np.array([zl]), z0, np.array([0.0]), np.array([beta]), 2.5)
    half = transform_through_line(np.array([zl]), z0, np.array([0.0]), np.array([beta]), 5.0)
    assert quarter[0] == pytest.approx(z0 * z0 / zl, rel=1e-9)
    assert half[0] == pytest.approx(zl, rel=1e-9)


def test_feed_system_matched_line_loss():
    f = np.array([14.0])
    cfg = {"transformer_ratio": 1.0, "coax": "rg213", "length": 30.48, "z0": 50.0}
    res = apply_feed_system(f, np.array([50 + 0j]), cfg)
    expected = COAX["rg213"].matched_loss_db_per_m(14.0) * 30.48
    assert res.matched_loss_db[0] == pytest.approx(expected)
    assert res.total_loss_db[0] == pytest.approx(expected, rel=1e-6)
    mismatched = apply_feed_system(f, np.array([200 + 0j]), cfg)
    assert mismatched.total_loss_db[0] > expected


def test_coax_loss_matches_reference_points():
    c = COAX["rg58"]
    assert c.matched_loss_db_per_m(10) * 30.48 == pytest.approx(1.4, rel=1e-6)
    assert c.matched_loss_db_per_m(100) * 30.48 == pytest.approx(4.9, rel=1e-6)


def test_transformer_ratio():
    cfg = {"transformer_ratio": 9.0, "coax": "none", "length": 0.0, "z0": 50.0}
    res = apply_feed_system(np.array([7.0]), np.array([450 + 90j]), cfg)
    assert res.z_rig[0] == pytest.approx(50 + 10j)


def test_wheeler_textbook_value():
    # 1" diameter, 1" long, 10 turns -> 100 / 58 µH
    assert wheeler_inductance_uh(10, 0.0254, 0.0254) == pytest.approx(100 / 58)


def test_coil_design_round_trip():
    c = design_coil(20.0, form_diameter_m=0.05, wire_diameter_m=1.5e-3)
    assert c.inductance_uh == pytest.approx(20.0, rel=1e-6)
    assert c.coil_length_m == pytest.approx(c.turns * 1.5e-3)


def test_ground_loss_decreases_with_radials():
    r0 = estimate_ground_loss(0, 0, 7.0, "average")
    r4 = estimate_ground_loss(4, 10.7, 7.0, "average")
    r32 = estimate_ground_loss(32, 10.7, 7.0, "average")
    r120 = estimate_ground_loss(120, 10.7, 7.0, "average")
    assert r0 > r4 > r32 > r120 > 0
    assert r4 == pytest.approx(30, abs=5)
    assert estimate_ground_loss(4, 10.7, 7.0, "salt_water") < r4


def test_find_root_bracketed_and_scanned():
    r = find_root(lambda x: x ** 3 - 8, 0.0, 5.0, tol_x=1e-6, tol_f=1e-6)
    assert r.converged and r.value == pytest.approx(2.0, abs=1e-4)
    # No sign change at the ends, root inside found by scanning.
    r = find_root(lambda x: (x - 1.0) * (x - 4.0), 0.0, 5.0, tol_x=1e-6, tol_f=1e-6)
    assert r.converged
    assert min(abs(r.value - 1.0), abs(r.value - 4.0)) < 1e-3
    r = find_root(lambda x: x * x + 1, -1.0, 1.0, tol_x=1e-6)
    assert not r.converged
