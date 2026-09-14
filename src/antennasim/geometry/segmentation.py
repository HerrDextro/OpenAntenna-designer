"""Automatic wire segmentation."""

from __future__ import annotations

import math

from ..model.units import wavelength_m
from .wire_model import WireModel


def target_segment_length(freq_max_mhz: float, segments_per_wavelength: int) -> float:
    return wavelength_m(freq_max_mhz) / segments_per_wavelength


def segment(model: WireModel, freq_max_mhz: float, segments_per_wavelength: int) -> WireModel:
    """Fill in `segments` for every wire that has it set to 0.

    Uses a uniform target segment length so segments on either side of a
    junction match, which keeps NEC2 accurate at junctions and at the feed.
    """
    target = target_segment_length(freq_max_mhz, segments_per_wavelength)
    for wire in model.wires:
        if wire.segments <= 0:
            wire.segments = max(1, math.ceil(wire.length / target - 1e-9))
    return model
