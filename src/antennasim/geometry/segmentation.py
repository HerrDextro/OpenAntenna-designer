"""Automatic wire segmentation."""

from __future__ import annotations

import math

from ..model.units import wavelength_m
from .wire_model import WireModel

# Segments across the antenna's largest dimension, however small it is in
# wavelengths. A short loaded antenna needs this many to place its coils and
# resolve the current; λ/20 alone gave a 0.29 λ loaded dipole only 8 segments
# and tuned its coils 8% high.
SEGMENTS_ACROSS = 40

# Thin-wire validity: keep segments well above the wire radius.
MIN_SEGMENT_PER_RADIUS = 8.0


def target_segment_length(freq_max_mhz: float, segments_per_wavelength: int) -> float:
    return wavelength_m(freq_max_mhz) / segments_per_wavelength


def model_size(model: WireModel) -> float:
    """Diagonal of the model's bounding box, in metres."""
    lo, hi = model.bounds()
    return math.dist(lo, hi)


def choose_segment_length(model: WireModel, freq_max_mhz: float,
                          segments_per_wavelength: int) -> float:
    """Target segment length: fine enough for both the wavelength and the antenna.

    Electrically large antennas are limited by the wavelength rule; physically
    small ones get at least SEGMENTS_ACROSS segments across their size. Never
    shorter than the thin-wire limit allows for the fattest conductor.
    """
    by_wavelength = target_segment_length(freq_max_mhz, segments_per_wavelength)
    by_size = model_size(model) / SEGMENTS_ACROSS
    target = min(by_wavelength, by_size) if by_size > 0 else by_wavelength
    fattest = max((w.radius for w in model.wires), default=0.0)
    return min(max(target, MIN_SEGMENT_PER_RADIUS * fattest), by_wavelength)


def segment(model: WireModel, target_length: float) -> WireModel:
    """Fill in `segments` for every wire that has it set to 0.

    Uses a uniform target segment length so segments on either side of a
    junction match, which keeps NEC2 accurate at junctions and at the feed.
    """
    for wire in model.wires:
        if wire.segments <= 0:
            wire.segments = max(1, math.ceil(wire.length / target_length - 1e-9))
    return model
