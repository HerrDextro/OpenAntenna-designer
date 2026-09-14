"""NEC2 card deck generation."""

from __future__ import annotations

import math

from ..geometry.wire_model import GroundModel, WireModel


def _num(x: float) -> str:
    return f"{x:.7g}"


def _geometry_cards(model: WireModel) -> list[str]:
    cards = []
    for i, w in enumerate(model.wires):
        coords = " ".join(_num(c) for c in (*w.p1, *w.p2))
        cards.append(f"GW {i + 1} {max(w.segments, 1)} {coords} {_num(w.radius)}")
    return cards


def _ground_cards(ground: GroundModel) -> list[str]:
    if ground.kind == "free_space":
        return ["GE 0"]
    if ground.kind == "perfect":
        return ["GE 1", "GN 1"]
    return ["GE 1", f"GN 2 0 0 0 {_num(ground.permittivity)} {_num(ground.conductivity)}"]


def _load_cards(model: WireModel, freq_mhz: float) -> list[str]:
    cards = []
    if math.isfinite(model.conductivity):
        cards.append(f"LD 5 0 0 0 {_num(model.conductivity)}")
    for load in model.loads:
        seg = model.wires[load.wire].segment_at(load.fraction)
        tag = load.wire + 1
        cards.append(f"LD 0 {tag} {seg} {seg} {_num(load.resistance_at(freq_mhz))} "
                     f"{_num(load.l_uh * 1e-6)} 0")
    return cards


def _source_card(model: WireModel) -> str:
    src = model.source
    seg = model.wires[src.wire].segment_at(src.fraction)
    return f"EX 0 {src.wire + 1} {seg} 0 1 0"


def solver_deck(model: WireModel, sweep_mhz: list[float], design_mhz: float,
                title: str = "AntennaSim") -> str:
    """Deck with one execution block per frequency.

    Blocks are separate so frequency-dependent loads (coil loss R = X_L/Q)
    are correct at every point. Currents are printed only for the design
    frequency, which is always the last block.
    """
    cards = [f"CM {title}", "CE", *_geometry_cards(model), *_ground_cards(model.ground)]
    freqs = [(f, False) for f in sweep_mhz] + [(design_mhz, True)]
    for i, (freq, print_currents) in enumerate(freqs):
        if i > 0:
            cards.append("LD -1")
        cards += _load_cards(model, freq)
        if i == 0:
            cards.append(_source_card(model))
        cards.append("PT 0" if print_currents else "PT -1")
        cards.append(f"FR 0 1 0 0 {_num(freq)} 0")
        cards.append("XQ")
    cards.append("EN")
    return "\n".join(cards) + "\n"


def export_deck(model: WireModel, sweep_start: float, sweep_stop: float, points: int,
                design_mhz: float, title: str, comments: list[str] = ()) -> str:
    """A conventional single-sweep deck for use in 4nec2, EZNEC import, etc.

    Coil loss resistance is fixed at its design-frequency value.
    """
    cards = [f"CM {title}"] + [f"CM {c}" for c in comments] + ["CE"]
    cards += _geometry_cards(model)
    cards += _ground_cards(model.ground)
    cards += _load_cards(model, design_mhz)
    cards.append(_source_card(model))
    step = (sweep_stop - sweep_start) / max(points - 1, 1)
    cards.append(f"FR 0 {points} 0 0 {_num(sweep_start)} {_num(step)}")
    cards.append(f"FR 0 1 0 0 {_num(design_mhz)} 0")
    theta_stop = 90 if model.ground.kind != "free_space" else 180
    cards.append(f"RP 0 {theta_stop // 2 + 1} 73 1000 0 0 2 5")
    cards.append("EN")
    return "\n".join(cards) + "\n"
