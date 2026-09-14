"""Physical constants and display unit conversion."""

from __future__ import annotations

C0 = 299_792_458.0  # m/s

METRIC = "metric"
IMPERIAL = "imperial"


def wavelength_m(freq_mhz: float) -> float:
    return C0 / (freq_mhz * 1e6)


# (label, metres per display unit)
_LENGTH_UNITS = {
    METRIC: {"length": ("m", 1.0), "small_length": ("mm", 1e-3)},
    IMPERIAL: {"length": ("ft", 0.3048), "small_length": ("in", 0.0254)},
}

_FIXED_UNITS = {
    "angle": "°",
    "frequency": "MHz",
    "inductance": "µH",
    "resistance": "Ω",
}


def unit_label(kind: str, system: str) -> str:
    if kind in _LENGTH_UNITS[system]:
        return _LENGTH_UNITS[system][kind][0]
    return _FIXED_UNITS.get(kind, "")


def to_display(kind: str, value: float, system: str) -> float:
    if kind in _LENGTH_UNITS[system]:
        return value / _LENGTH_UNITS[system][kind][1]
    return value


def from_display(kind: str, value: float, system: str) -> float:
    if kind in _LENGTH_UNITS[system]:
        return value * _LENGTH_UNITS[system][kind][1]
    return value


def format_length(value_m: float, system: str, digits: int = 3) -> str:
    label = unit_label("length", system)
    return f"{to_display('length', value_m, system):.{digits}f} {label}"
