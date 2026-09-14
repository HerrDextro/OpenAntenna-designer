import math

import pytest

from antennasim.engine import SimulationBlocked, build, simulate, solve_impedance, tune
from antennasim.fileio.nec_export import export_nec
from antennasim.fileio.project_file import load_project, save_project
from antennasim.geometry.validation import ERROR, WARNING
from antennasim.model.document import NODE_ANTENNA, Project
from antennasim.model.units import wavelength_m


def grounded_vertical(ground="perfect", height=5.1, **antenna):
    p = Project.new("monopole")
    for part in list(p.parts):
        p.remove_part(part.id)
    p.antenna.update(feed_height=0.0, height=height, diameter=2e-3, **antenna)
    p.environment["ground"] = ground
    p.environment["conductor"] = "perfect"
    p.feedline["coax"] = "none"
    return p


def errors(built):
    return [i for i in built.issues if i.level == ERROR]


def test_default_project_simulates(backend):
    s = simulate(Project.new("monopole"), backend)
    assert 20 < s.summary.z_antenna.real < 90
    assert s.summary.resonances_mhz
    assert -5 < s.summary.max_gain_dbi < 5
    assert 5 < s.summary.takeoff_deg < 45
    assert 0.9 < s.summary.efficiency <= 1.0


def test_grounded_quarter_wave_perfect(backend):
    z = solve_impedance(grounded_vertical(), backend, 14.2)
    assert z.real == pytest.approx(36, abs=3)


def test_grounded_over_real_ground_uses_perfect_plus_loss(backend):
    p = grounded_vertical("real")
    p.add_part("radials", {"mode": "buried", "count": 16, "length": 5.3})
    built = build(p)
    assert not errors(built)
    assert built.solve_ground.kind == "perfect"
    assert built.model.ground.kind == "real"
    assert built.ground_loss_ohm > 0
    s = simulate(p, backend)
    assert s.summary.z_antenna.real == pytest.approx(36 + built.ground_loss_ohm, abs=4)
    # Real ground: no gain at the horizon, efficiency reduced by ground loss.
    assert s.pattern.gain_total_dbi[-1].max() < -20
    assert s.summary.efficiency < 0.9


def test_top_hat_lowers_resonance(backend):
    plain = grounded_vertical(height=4.0)
    hat = grounded_vertical(height=4.0)
    hat.add_part("top_hat", {"spokes": 4, "length": 1.0, "ring": True})
    for p in (plain, hat):
        p.simulation.update(sweep_start=5.0, sweep_stop=22.0, sweep_points=35)
    f_plain = simulate(plain, backend).summary.resonances_mhz[0]
    f_hat = simulate(hat, backend).summary.resonances_mhz[0]
    assert f_hat < f_plain * 0.9


def test_loading_coil_lowers_resonance_and_adds_loss(backend):
    plain = grounded_vertical(height=4.0)
    coil = grounded_vertical(height=4.0)
    coil.add_part("loading_coil", {"height": 0.0, "inductance": 5.0, "q": 100})
    for p in (plain, coil):
        p.simulation.update(sweep_start=8.0, sweep_stop=22.0, sweep_points=29)
    s_plain, s_coil = simulate(plain, backend), simulate(coil, backend)
    assert s_coil.summary.resonances_mhz[0] < s_plain.summary.resonances_mhz[0]
    assert s_coil.summary.efficiency < s_plain.summary.efficiency
    coil_wires = [w for w in s_coil.built.model.wires if w.name == "Loading coil"]
    assert len(coil_wires) == 1 and coil_wires[0].segments == 1


def test_coil_in_middle_splits_element():
    p = grounded_vertical(height=6.0)
    p.add_part("loading_coil", {"height": 3.0, "inductance": 10.0})
    wires = build(p).model.wires
    names = [w.name for w in wires]
    assert names == ["Vertical element", "Loading coil", "Vertical element"]
    assert sum(w.length for w in wires) == pytest.approx(6.0)
    assert (wires[1].p1[2] + wires[1].p2[2]) / 2 == pytest.approx(3.0)


def test_inverted_l_geometry_and_resonance(backend):
    p = grounded_vertical(height=3.0, top_length=2.5, top_azimuth=90.0)
    wires = build(p).model.wires
    assert wires[1].name == "Horizontal section"
    assert wires[1].p2 == pytest.approx((0.0, 2.5, 3.0), abs=1e-9)
    p.simulation.update(sweep_start=10.0, sweep_stop=20.0, sweep_points=21)
    s = simulate(p, backend)
    assert s.summary.resonances_mhz  # roughly quarter wave overall (5.5 m)


def test_validation_blocks_impossible_designs(backend):
    p = grounded_vertical("real")
    p.antenna["feed_height"] = 2.0  # elevated feed with no radials
    assert errors(build(p))
    with pytest.raises(SimulationBlocked):
        simulate(p, backend)

    p = grounded_vertical("real")
    p.add_part("radials", {"mode": "wires"})  # radials on the ground
    assert errors(build(p))

    p = Project.new("monopole")
    p.part("radials1").params.update(mode="buried")  # buried with elevated feed
    assert errors(build(p))

    p = Project.new("monopole")
    p.part("radials1").params.update(droop=80.0, length=5.0)
    p.antenna["feed_height"] = 1.0
    assert errors(build(p))  # radial tips below ground


def test_coarse_segmentation_warns():
    p = Project.new("monopole")
    p.simulation["segments_per_wavelength"] = 100
    p.simulation["sweep_stop"] = 30.0
    p.antenna["diameter"] = 0.3  # 0.1 m segments on a 0.15 m radius tube
    assert any(i.level == WARNING for i in build(p).issues)


def test_segment_length_follows_frequency():
    p = Project.new("monopole")
    built = build(p)
    target = wavelength_m(p.simulation["sweep_stop"]) / p.simulation["segments_per_wavelength"]
    for w in built.model.wires:
        assert w.length / w.segments <= target + 1e-9


def test_tune_height_to_resonance(backend):
    p = grounded_vertical(height=4.5)
    tunable = next(t for t in p.template.tunables(p) if t.key == "height")
    result = tune(p, tunable, backend, 14.2)
    assert result.converged
    p.set_value(NODE_ANTENNA, "height", result.value)
    assert abs(solve_impedance(p, backend, 14.2).imag) < 2
    assert 4.7 < result.value < 5.3


def test_handles_edit_values():
    p = Project.new("monopole")
    h = next(h for h in p.template.handles(p) if h.key == "height" and h.view == "side")
    dx, dy = 0.0, 0.5
    assert h.value + dx * h.axis[0] + dy * h.axis[1] == pytest.approx(p.antenna["height"] + 0.5)
    r = next(h for h in p.template.handles(p) if h.key == "length" and h.view == "top")
    # Dragging along the radial in the top view by its projected length of 1 m.
    params = p.part("radials1").params
    droop, az = math.radians(params["droop"]), math.radians(params["azimuth"])
    dx, dy = math.cos(az) * math.cos(droop), math.sin(az) * math.cos(droop)
    assert r.value + dx * r.axis[0] + dy * r.axis[1] == pytest.approx(r.value + 1.0)


def test_project_round_trip(tmp_path):
    p = Project.new("monopole")
    p.add_part("top_hat", {"spokes": 6})
    p.add_part("loading_coil", {"inductance": 12.5})
    p.antenna["top_length"] = 2.0
    path = tmp_path / "x.antsim"
    save_project(p, path)
    q = load_project(path)
    assert q.to_dict() == p.to_dict()


def test_nec_export_runs(tmp_path, backend):
    p = Project.new("monopole")
    p.add_part("loading_coil", {"height": 1.0})
    text = export_nec(p, tmp_path / "x.nec")
    assert "GW 1" in text and "EX 0" in text and "RP 0" in text and text.endswith("EN\n")
    from .conftest import parse_rp_total_gain, run_nec_raw

    assert parse_rp_total_gain(run_nec_raw(text))
