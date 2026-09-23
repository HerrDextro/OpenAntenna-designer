import math

import pytest

from antennasim.engine import build, simulate, solve_impedance, tune
from antennasim.geometry.validation import ERROR, WARNING
from antennasim.model.document import NODE_ANTENNA, Project


def dipole(ground="free_space", **antenna):
    p = Project.new("dipole")
    p.antenna.update(antenna)
    p.environment["ground"] = ground
    p.environment["conductor"] = "perfect"
    p.feedline["coax"] = "none"
    return p


def test_free_space_half_wave_reference(backend):
    p = dipole(leg_length=5.1, diameter=2e-3)
    z = solve_impedance(p, backend, 14.2)
    assert z.real == pytest.approx(73, abs=5)
    assert abs(z.imag) < 20


def test_geometry_two_legs_and_centre_feed():
    p = dipole(leg_length=5.0, height=8.0, azimuth=90.0)
    model = build(p).model
    assert [w.name for w in model.wires] == ["Leg 1", "Leg 2"]
    assert model.wires[0].p1 == pytest.approx((0.0, 0.0, 8.0))
    assert model.wires[0].p2 == pytest.approx((0.0, 5.0, 8.0), abs=1e-9)
    assert model.wires[1].p2 == pytest.approx((0.0, -5.0, 8.0), abs=1e-9)
    assert model.source.wire == 0 and model.source.fraction == 0.0


def test_inverted_v_drops_ends_and_impedance(backend):
    flat = dipole("real", leg_length=5.1, height=10.0)
    vee = dipole("real", leg_length=5.1, height=10.0, droop=40.0)
    tips = [w.p2[2] for w in build(vee).model.wires]
    assert all(t == pytest.approx(10.0 - 5.1 * math.sin(math.radians(40))) for t in tips)
    # An inverted V has a lower feed impedance than the same flat dipole.
    assert solve_impedance(vee, backend, 14.2).real < solve_impedance(flat, backend, 14.2).real


def test_symmetric_coils_shorten_the_antenna(backend):
    plain = dipole("free_space", leg_length=3.0)
    loaded = dipole("free_space", leg_length=3.0)
    loaded.add_part("loading_coil", {"height": 1.5, "inductance": 5.0, "q": 200})
    model = build(loaded).model
    coils = [w for w in model.wires if w.name == "Loading coil"]
    assert len(coils) == 2  # one per leg
    assert all(w.segments == 1 for w in coils)
    for p in (plain, loaded):
        p.simulation.update(sweep_start=8.0, sweep_stop=25.0, sweep_points=35)
    assert (simulate(loaded, backend).summary.resonances_mhz[0]
            < simulate(plain, backend).summary.resonances_mhz[0])


def test_tune_leg_length(backend):
    p = dipole("real", leg_length=4.5, height=10.0)
    tunable = next(t for t in p.template.tunables(p) if t.key == "leg_length")
    result = tune(p, tunable, backend, 14.2)
    assert result.converged
    p.set_value(NODE_ANTENNA, "leg_length", result.value)
    assert abs(solve_impedance(p, backend, 14.2).imag) < 2
    assert 4.7 < result.value < 5.3


def test_validation_below_ground_and_low_height():
    p = dipole("real", leg_length=5.0, height=2.0, droop=60.0)
    assert any(i.level == ERROR for i in build(p).issues)
    p = dipole("real", leg_length=5.0, height=2.0)
    assert any(i.level == WARNING for i in build(p).issues)
    assert not [i for i in build(p).issues if i.level == ERROR]


def test_over_ground_simulation_and_pattern(backend):
    p = dipole("real", leg_length=5.05, height=10.0)
    s = simulate(p, backend)
    assert 40 < s.summary.z_antenna.real < 110
    assert s.summary.max_gain_dbi > 3  # ground reflection gain
    assert 20 < s.summary.takeoff_deg < 60
    assert s.pattern.gain_total_dbi[-1].max() < -10  # null at the horizon


def test_handles_and_cut_list():
    p = dipole(leg_length=5.0, droop=30.0)
    handles = p.template.handles(p)
    assert {h.key for h in handles} == {"height", "leg_length"}
    side = [h for h in handles if h.view == "side" and h.key == "leg_length"]
    assert len(side) == 2
    dr = math.radians(30.0)
    dx, dz = math.cos(dr), -math.sin(dr)  # move 1 m along leg 1
    assert side[0].value + dx * side[0].axis[0] + dz * side[0].axis[1] == pytest.approx(6.0)
    items = p.template.cut_list(p)
    assert items[0].quantity == 2 and items[0].length_m == pytest.approx(5.0)
