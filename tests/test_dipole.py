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


def test_vertical_dipole_geometry():
    p = dipole("real", leg_length=2.6, height=5.0, tilt=90.0)
    wires = build(p).model.wires
    upper, lower = wires[0].p2, wires[-1].p2
    assert upper == pytest.approx((0.0, 0.0, 7.6), abs=1e-9)
    assert lower == pytest.approx((0.0, 0.0, 2.4), abs=1e-9)
    assert build(p).model.source.wire == 0  # still fed at the centre


def test_sloper_lifts_one_leg_and_lowers_the_other():
    p = dipole("real", leg_length=4.0, height=8.0, tilt=30.0)
    wires = build(p).model.wires
    rise = 4.0 * math.sin(math.radians(30))
    assert wires[0].p2[2] == pytest.approx(8.0 + rise)
    assert wires[-1].p2[2] == pytest.approx(8.0 - rise)


def test_tilt_does_not_matter_in_free_space(backend):
    # Free space has no preferred direction, so standing the dipole up must not
    # change its impedance.
    flat = solve_impedance(dipole("free_space", leg_length=5.1), backend, 14.2)
    upright = solve_impedance(dipole("free_space", leg_length=5.1, tilt=90.0), backend, 14.2)
    assert upright.real == pytest.approx(flat.real, abs=0.5)
    assert upright.imag == pytest.approx(flat.imag, abs=0.5)


def test_vertical_dipole_over_ground_is_vertically_polarised(backend):
    import numpy as np

    flat = simulate(dipole("real", leg_length=5.05, height=10.0), backend)
    upright = simulate(dipole("real", leg_length=5.05, height=10.0, tilt=90.0), backend)
    pat = upright.pattern
    assert np.max(pat.gain_vert_dbi) > np.max(pat.gain_hor_dbi) + 10
    # A vertical radiates toward the horizon; a horizontal dipole at 0.47 lambda
    # fires much higher.
    assert upright.summary.takeoff_deg < flat.summary.takeoff_deg
    # And it is omnidirectional in azimuth, unlike the horizontal one.
    assert upright.summary.azimuth_variation_db < 0.2
    assert flat.summary.azimuth_variation_db > 3


def test_vertical_dipole_validation():
    too_low = dipole("real", leg_length=2.6, height=2.0, tilt=90.0)
    assert any(i.level == ERROR for i in build(too_low).issues)  # lower leg in the soil

    ok = dipole("real", leg_length=2.6, height=3.5, tilt=90.0)
    issues = build(ok).issues
    assert not [i for i in issues if i.level == ERROR]
    # The "low feed point, high take-off angle" warning is about horizontal
    # dipoles and must not fire for a vertical one.
    assert not any("take-off angle" in i.message and "under 0.15" in i.message for i in issues)


def test_vertical_dipole_handles_follow_the_legs():
    p = dipole(leg_length=2.6, height=5.0, tilt=90.0)
    p.add_part("loading_coil", {"height": 0.8, "inductance": 2.0})
    handles = p.template.handles(p)
    side_legs = [h for h in handles if h.view == "side" and h.key == "leg_length"]
    assert len(side_legs) == 2
    assert not [h for h in handles if h.view == "top" and h.key == "leg_length"]
    upper = max(side_legs, key=lambda h: h.pos[1])
    # Dragging the upper tip up by 0.5 m lengthens the leg by 0.5 m.
    assert upper.value + 0.5 * upper.axis[1] == pytest.approx(3.1)
    coil = [h for h in handles if h.key == "height" and h.node_id != "antenna"]
    assert coil and coil[0].view == "side"


def test_loaded_vertical_cb_dipole_tunes(backend):
    # The build being planned: a short centre-fed vertical dipole for 27.085 MHz,
    # shortened with a coil in each leg.
    p = dipole("real", leg_length=1.6, height=4.0, tilt=90.0)
    p.simulation.update(design_mhz=27.085, sweep_start=26.5, sweep_stop=27.6)
    p.add_part("loading_coil", {"height": 0.4, "inductance": 1.0, "q": 200})
    tunable = next(t for t in p.template.tunables(p) if t.key == "inductance")
    result = tune(p, tunable, backend, 27.085)
    assert result.converged, result.message
    p.set_value(tunable.node_id, "inductance", result.value)
    z = solve_impedance(p, backend, 27.085)
    assert abs(z.imag) < 2
    assert 0.5 < result.value < 10  # a few µH per leg, as expected at CB


def test_short_loaded_antenna_is_segmented_finely_enough(backend):
    # At 0.29 lambda tall, the wavelength rule alone gave this antenna 8 segments
    # and tuned its coils 8% high. Default settings must now agree with a far
    # finer model.
    def tuned(spw):
        p = dipole("real", leg_length=1.6, height=4.0, tilt=90.0, diameter=0.008)
        p.simulation.update(design_mhz=27.085, sweep_start=26.5, sweep_stop=27.7,
                            segments_per_wavelength=spw)
        p.add_part("loading_coil", {"height": 0.4, "inductance": 1.0, "q": 200})
        tunable = next(t for t in p.template.tunables(p) if t.key == "inductance")
        return tune(p, tunable, backend, 27.085).value, build(p)

    default_l, default_build = tuned(20)
    fine_l, _ = tuned(160)
    assert default_l == pytest.approx(fine_l, rel=0.02)
    assert sum(w.segments for w in default_build.model.wires) >= 30


def test_coil_stand_in_wire_is_not_flagged_as_fat():
    p = dipole("real", leg_length=1.6, height=4.0, tilt=90.0, diameter=0.008)
    p.simulation.update(design_mhz=27.085, sweep_start=26.5, sweep_stop=27.7)
    p.add_part("loading_coil", {"height": 0.4, "inductance": 1.7})
    assert not any("fat conductor" in i.message for i in build(p).issues)
    # A genuinely fat element is still reported.
    stubby = dipole("free_space", leg_length=0.3, diameter=0.05)
    assert any("fat conductor" in i.message for i in build(stubby).issues)
