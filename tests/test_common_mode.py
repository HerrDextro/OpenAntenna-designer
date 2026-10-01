import math

import pytest

from antennasim.analysis.coil import air_choke
from antennasim.analysis.common_mode import MET, NEEDS, UNREACHABLE
from antennasim.engine import build, simulate, solve_impedance
from antennasim.fileio.project_file import load_project, save_project
from antennasim.geometry.validation import ERROR, INFO, segment_distance
from antennasim.model.document import NODE_FEEDLINE, Project
from antennasim.templates import coax


def cb_vertical(**feedline):
    """The 27 MHz loaded vertical dipole, fed with RG-58 whose shield is modelled."""
    p = Project.new("dipole")
    p.antenna.update(leg_length=2.3, height=3.3, tilt=90.0, diameter=0.008)
    p.add_part("loading_coil", {"height": 0.4, "inductance": 0.562, "q": 200})
    p.simulation.update(design_mhz=27.085, sweep_start=26.5, sweep_stop=27.7, sweep_points=7)
    p.feedline.update({"coax": "rg58", "common_mode": True, **feedline})
    return p


def flat_dipole():
    p = Project.new("dipole")
    p.antenna.update(leg_length=5.05, height=10.0, azimuth=90.0)
    p.simulation.update(sweep_points=5)
    p.environment["conductor"] = "perfect"
    p.feedline.update(coax="rg213", common_mode=True, radio_height=0.5)
    return p


def errors(built):
    return [i for i in built.issues if i.level == ERROR]


def test_shield_is_off_by_default_and_parts_wait_for_it():
    p = Project.new("dipole")
    assert not p.can_add_part("coax_run")  # inactive until the shield is modelled
    names = [w.name for w in build(p).model.wires]
    p.feedline["common_mode"] = True
    assert p.can_add_part("coax_run") and p.can_add_part("choke")
    assert p.part_allowed("choke") and Project.new("monopole").part_allowed("choke")
    built = build(p)
    assert built.shield is not None
    assert [w.name for w in built.model.wires][:len(names)] == names
    shield = built.model.wires[built.shield.wires[0]]
    assert shield.p1 == pytest.approx((0.0, 0.0, 10.0))  # starts at the feed point
    assert shield.p2 == pytest.approx((0.0, 0.0, 1.0))  # straight down to the radio


def test_route_follows_runs_and_sets_feedline_length():
    p = cb_vertical(extra_length=2.0)
    p.add_part("coax_run", {"length": 1.0, "azimuth": 90.0})
    p.add_part("coax_run", {"length": 0.5, "slope": 90.0})
    legs = coax.route(p)
    assert [leg.name for leg in legs] == ["Coax run 1", "Coax run 2", "Coax to radio"]
    assert legs[0].p2 == pytest.approx((0.0, 1.0, 3.3), abs=1e-9)
    assert legs[1].p2 == pytest.approx((0.0, 1.0, 2.8), abs=1e-9)
    assert legs[2].p2 == pytest.approx((0.0, 1.0, 1.0), abs=1e-9)
    assert coax.feedline_length(p) == pytest.approx(1.0 + 0.5 + 1.8 + 2.0)
    assert p.part_label(p.parts_of("coax_run")[1]) == "Coax run 2"


def test_coax_does_not_change_antenna_segmentation():
    plain = cb_vertical(common_mode=False)
    routed = cb_vertical()
    routed.add_part("coax_run", {"length": 1.0})
    routed.add_part("coax_run", {"length": 15.0, "azimuth": 90.0})
    a, b = build(plain).model.wires, build(routed).model.wires
    assert [w.segments for w in a] == [w.segments for w in b[:len(a)]]


def test_coax_alongside_the_lower_leg_is_rejected():
    p = cb_vertical()
    assert any("runs along Leg 2" in i.message for i in errors(build(p)))
    p.add_part("coax_run", {"length": 0.5})
    assert not errors(build(p))
    # A bend exactly on an antenna wire's end would connect the two in NEC2.
    q = flat_dipole()
    q.add_part("coax_run", {"length": 1.0, "slope": 90.0})
    q.add_part("coax_run", {"length": 5.05, "azimuth": 90.0})
    q.add_part("coax_run", {"length": 1.0, "slope": -90.0})  # up to the tip of leg 1
    assert any("ends exactly on the end of Leg 1" in i.message for i in errors(build(q)))


def test_feedline_type_and_ground_checks():
    ladder = cb_vertical(coax="ladder450")
    assert any("no shield" in i.message for i in errors(build(ladder)))
    assert build(ladder).shield is None
    none = cb_vertical(coax="none")
    assert any("coax type" in i.message for i in errors(build(none)))
    free = flat_dipole()
    free.environment["ground"] = "free_space"
    free.feedline["radio_end"] = "earthed"
    assert any("earthed radio" in i.message for i in errors(build(free)))

    grounded = Project.new("monopole")
    grounded.antenna["feed_height"] = 0.0
    grounded.part("radials1").params["mode"] = "buried"
    grounded.feedline.update(coax="rg58", common_mode=True)
    built = build(grounded)
    assert built.shield is None
    assert any(i.level == INFO and "bonded" in i.message for i in built.issues)


def test_earthed_radio_adds_an_earth_lead():
    p = cb_vertical(radio_end="earthed", earth_resistance=30.0)
    p.add_part("coax_run", {"length": 1.0})
    built = build(p)
    lead = built.model.wires[built.shield.earth_wire]
    assert lead.p1[2] == pytest.approx(1.0) and lead.p2[2] == pytest.approx(0.0)
    assert any(ld.name == "Earth connection" and ld.r_ohm == 30.0 for ld in built.model.loads)
    assert not errors(built)


def test_unbalanced_feed_puts_current_on_a_perpendicular_coax(backend):
    # A coax hanging straight down from a flat dipole picks up no field-induced
    # current by symmetry, but the shield is wired to one leg only, so a few
    # percent still flows. This is what a 1:1 current balun is for.
    p = flat_dipole()
    p.feedline["cm_target"] = 1.0
    cm = simulate(p, backend).summary.common_mode
    assert 0.005 < cm.at_feed < 0.2
    assert cm.requirement.status == NEEDS


def test_perfect_choke_restores_the_balanced_dipole(backend):
    plain = flat_dipole()
    plain.feedline["common_mode"] = False
    choked = flat_dipole()
    choked.add_part("choke", {"choke_type": "perfect"})
    z_plain = solve_impedance(plain, backend, 14.2)
    z_choked = solve_impedance(choked, backend, 14.2)
    assert abs(z_choked - z_plain) < 1.0
    cm = simulate(choked, backend).summary.common_mode
    assert cm.peak < 0.01
    assert cm.chokes and abs(cm.chokes[0][2]) >= coax.PERFECT_CHOKE_OHM * 0.99


def test_choke_requirement_matches_a_direct_simulation(backend):
    p = cb_vertical()
    p.add_part("coax_run", {"length": 1.0})
    cm = simulate(p, backend).summary.common_mode
    req = cm.requirement
    assert req.status == NEEDS
    assert req.unchoked_ratio > 0.1 > req.perfect_ratio
    # Put exactly that choke in and simulate for real: the target is met, just.
    p.add_part("choke", {"choke_type": "impedance", "r_ohm": req.resistance_ohm, "x_ohm": 0.0})
    choked = simulate(p, backend).summary.common_mode
    assert choked.peak == pytest.approx(0.1, rel=1e-3)
    # And a perfect choke leaves exactly what was predicted.
    p.part("choke1").params["choke_type"] = "perfect"
    assert simulate(p, backend).summary.common_mode.peak == pytest.approx(req.perfect_ratio,
                                                                         rel=1e-3)


def test_requirement_reports_met_and_unreachable(backend):
    far = cb_vertical(cm_target=50.0)
    far.add_part("coax_run", {"length": 2.7})
    assert simulate(far, backend).summary.common_mode.requirement.status == MET

    # Coax 5 cm beside the lower leg: the leg's field induces current on it that
    # no choke at the feed can stop.
    close = cb_vertical(cm_target=1.0)
    close.add_part("coax_run", {"length": 0.05})
    req = simulate(close, backend).summary.common_mode.requirement
    assert req.status == UNREACHABLE and req.perfect_ratio > 0.01


def test_air_choke_model():
    # 14 turns of RG-58 on a 60 mm form: the choke that was built.
    coil = air_choke(14, 0.06, 4.95e-3, 50.0, 27.085)
    assert coil.inductance_uh == pytest.approx(8.3, abs=0.2)
    assert coil.capacitance_pf == pytest.approx(3.0, abs=0.3)
    assert coil.self_resonance_mhz == pytest.approx(32.0, abs=1.5)
    assert coil.impedance(20.0).imag > 0  # inductive below self-resonance
    assert coil.impedance(40.0).imag < 0  # capacitive above it
    assert coil.impedance(coil.self_resonance_mhz).real == pytest.approx(coil.resistance_ohm,
                                                                        rel=1e-6)


def test_air_choke_warnings():
    p = cb_vertical()
    p.add_part("coax_run", {"length": 1.0})
    p.add_part("choke", {"choke_type": "air_coil", "turns": 30, "form_diameter": 0.1})
    messages = [i.message for i in build(p).issues if i.node_id == "choke1"]
    assert any("above its self-resonance" in m for m in messages)
    p.part("choke1").params.update(turns=4, form_diameter=0.04)
    messages = [i.message for i in build(p).issues if i.node_id == "choke1"]
    assert not any("self-resonance." in m and "above" in m for m in messages)


def test_choke_position_along_the_route():
    p = cb_vertical()
    p.add_part("coax_run", {"length": 1.0})
    p.add_part("choke", {"distance": 1.5})
    built = build(p)
    load = next(ld for ld in built.model.loads if ld.part_id == "choke1")
    wire = built.model.wires[load.wire]
    assert wire.name == "Coax to radio"
    assert wire.p1[2] - (wire.p1[2] - wire.p2[2]) * load.fraction == pytest.approx(2.8)
    # Beyond the end it is clamped to the radio and flagged.
    p.part("choke1").params["distance"] = 50.0
    assert any("beyond the end" in i.message for i in build(p).issues)


def test_handles_edit_runs_chokes_and_radio_height():
    p = cb_vertical()
    p.add_part("coax_run", {"length": 1.0, "azimuth": 0.0})
    p.add_part("choke", {"distance": 0.5})
    handles = coax.handles(p)
    run = next(h for h in handles if h.node_id == "coax_run1" and h.view == "side")
    assert run.value + 0.4 * run.axis[0] == pytest.approx(1.4)
    radio = next(h for h in handles if h.key == "radio_height")
    assert radio.node_id == NODE_FEEDLINE and radio.pos[1] == pytest.approx(1.0)
    assert any(h.node_id == "choke1" for h in handles)
    p.feedline["common_mode"] = False
    assert coax.handles(p) == []


def test_cut_list_includes_the_coax_and_choke_windings():
    p = cb_vertical(extra_length=3.0)
    p.add_part("coax_run", {"length": 1.0})
    p.add_part("choke", {"choke_type": "air_coil", "turns": 10, "form_diameter": 0.05})
    items = coax.cut_items(p)
    winding = 10 * math.pi * (0.05 + 4.95e-3)
    assert items[0].name == "Coax"
    assert items[0].length_m == pytest.approx(1.0 + 2.3 + 3.0 + winding)
    assert items[1].length_m == pytest.approx(winding)


def test_project_round_trip_with_feed_parts(tmp_path):
    p = cb_vertical()
    p.add_part("coax_run", {"length": 1.0, "azimuth": 45.0})
    p.add_part("choke", {"choke_type": "impedance", "r_ohm": 2000.0, "x_ohm": -300.0})
    save_project(p, tmp_path / "x.antsim")
    assert load_project(tmp_path / "x.antsim").to_dict() == p.to_dict()


def test_segment_distance():
    assert segment_distance((0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)) == pytest.approx(1.0)
    assert segment_distance((0, 0, 0), (1, 0, 0), (0.5, -1, 1), (0.5, 1, 1)) == pytest.approx(1.0)
    assert segment_distance((0, 0, 0), (1, 0, 0), (2, 0, 0), (3, 0, 0)) == pytest.approx(1.0)
    assert segment_distance((0, 0, 0), (1, 0, 0), (0.5, -1, 0), (0.5, 1, 0)) == pytest.approx(0.0)
