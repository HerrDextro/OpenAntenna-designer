"""Reference impedances and far-field agreement with NEC2's own pattern output."""

import math

import numpy as np
import pytest

from antennasim.analysis.farfield import compute_pattern
from antennasim.geometry.wire_model import GroundModel, Source, Wire, WireModel
from antennasim.solver.base import SolveRequest
from antennasim.solver.nec_deck import _geometry_cards, _ground_cards, _source_card

from .conftest import parse_rp_total_gain, run_nec_raw


def dipole(half_length=5.1, radius=0.001, segs=21, height=None):
    z = height or 0.0
    m = WireModel()
    m.add_wire(Wire((0, -half_length, z), (0, half_length, z), radius, "Dipole", segments=segs))
    m.source = Source(0, 0.5)
    return m


def elevated_ground_plane(ground: GroundModel):
    m = WireModel(ground=ground)
    base = (0.0, 0.0, 3.0)
    m.add_wire(Wire(base, (0, 0, 8.1), 0.001, "Vertical", segments=21))
    for i in range(4):
        a = math.radians(90 * i)
        tip = (5.1 * math.cos(a) * math.cos(math.radians(30)),
               5.1 * math.sin(a) * math.cos(math.radians(30)),
               3.0 - 5.1 * math.sin(math.radians(30)))
        m.add_wire(Wire(base, tip, 0.001, f"Radial {i}", segments=21))
    m.source = Source(0, 0.0)
    return m


def test_quarter_wave_monopole_over_perfect_ground(backend):
    m = WireModel(ground=GroundModel("perfect"))
    m.add_wire(Wire((0, 0, 0), (0, 0, 5.1), 0.001, "Vertical", segments=21))
    m.source = Source(0, 0.0)
    z = backend.solve(SolveRequest(m, (), 14.2)).design.z_in
    assert z.real == pytest.approx(36, abs=2)
    assert abs(z.imag) < 10


def test_half_wave_dipole_free_space(backend):
    z = backend.solve(SolveRequest(dipole(), (), 14.2)).design.z_in
    assert z.real == pytest.approx(73, abs=4)
    assert abs(z.imag) < 15


def test_sweep_blocks_and_currents(backend):
    freqs = (13.0, 14.0, 15.0)
    res = backend.solve(SolveRequest(dipole(), freqs, 14.2))
    assert [r.freq_mhz for r in res.sweep] == pytest.approx(freqs)
    assert res.design.currents is not None and len(res.design.currents) == 21
    # Reactance rises with frequency through resonance.
    xs = [r.z_in.imag for r in res.sweep]
    assert xs[0] < xs[1] < xs[2]


def nec_pattern(model: WireModel, freq: float, rp: str) -> dict:
    deck = "\n".join(["CM t", "CE", *_geometry_cards(model), *_ground_cards(model.ground),
                      _source_card(model), f"FR 0 1 0 0 {freq} 0", rp, "EN"]) + "\n"
    return parse_rp_total_gain(run_nec_raw(deck))


@pytest.mark.parametrize("case", ["dipole_free", "gp_perfect", "gp_real"])
def test_farfield_matches_nec(backend, case):
    freq = 14.2
    if case == "dipole_free":
        model = dipole()
    elif case == "gp_perfect":
        model = elevated_ground_plane(GroundModel("perfect"))
    else:
        model = elevated_ground_plane(GroundModel("real", 0.005, 13.0))

    res = backend.solve(SolveRequest(model, (), freq))
    d = res.design
    ours = compute_pattern(model, d.currents, freq, d.power.input_w, model.ground,
                           theta_step=10.0, phi_step=45.0)
    theta_stop = 80 if model.ground.kind != "free_space" else 180
    n_theta = theta_stop // 10 + 1
    theirs = nec_pattern(model, freq, f"RP 0 {n_theta} 3 1000 0 0 10 45")
    assert theirs, "no NEC pattern parsed"

    compared = 0
    for (theta, phi), g_nec in theirs.items():
        if g_nec < -30:
            continue
        it = int(round(theta / 10))
        ip = int(round(phi / 45))
        assert ours.gain_total_dbi[it, ip] == pytest.approx(g_nec, abs=0.05), (theta, phi)
        compared += 1
    assert compared >= 5
