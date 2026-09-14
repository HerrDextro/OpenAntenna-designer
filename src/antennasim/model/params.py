"""Parameter specifications.

Every editable object (template, part, environment, feedline, frequency plan)
describes its fields with ParamSpec so the UI can build property editors
generically. Values are stored in base units:

    length / small_length  metres
    angle                  degrees
    frequency              MHz
    inductance             microhenries
    resistance             ohms
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

KINDS = {
    "length", "small_length", "angle", "frequency", "inductance", "resistance",
    "float", "int", "bool", "choice",
}


@dataclass(frozen=True)
class ParamSpec:
    key: str
    label: str
    kind: str
    default: Any
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[tuple[str, str], ...] = ()  # (value, label)
    help: str = ""
    # Only show this field when another field has one of the given values.
    visible_when: tuple[str, tuple[Any, ...]] | None = None

    def __post_init__(self):
        if self.kind not in KINDS:
            raise ValueError(f"unknown param kind {self.kind!r}")

    def coerce(self, value: Any) -> Any:
        if self.kind == "bool":
            return bool(value)
        if self.kind == "choice":
            valid = [c[0] for c in self.choices]
            return value if value in valid else self.default
        if self.kind == "int":
            value = int(round(float(value)))
        else:
            value = float(value)
        if self.minimum is not None:
            value = max(value, type(value)(self.minimum))
        if self.maximum is not None:
            value = min(value, type(value)(self.maximum))
        return value

    def is_visible(self, values: dict[str, Any]) -> bool:
        if self.visible_when is None:
            return True
        key, allowed = self.visible_when
        return values.get(key) in allowed


@dataclass
class ParamSet:
    """A group of values described by a list of specs."""

    specs: tuple[ParamSpec, ...]
    values: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        merged = {s.key: s.default for s in self.specs}
        for s in self.specs:
            if s.key in self.values:
                merged[s.key] = s.coerce(self.values[s.key])
        self.values = merged

    def spec(self, key: str) -> ParamSpec:
        for s in self.specs:
            if s.key == key:
                return s
        raise KeyError(key)

    def __getitem__(self, key: str) -> Any:
        return self.values[key]

    def set(self, key: str, value: Any) -> Any:
        coerced = self.spec(key).coerce(value)
        self.values[key] = coerced
        return coerced


def defaults(specs: tuple[ParamSpec, ...]) -> dict[str, Any]:
    return {s.key: s.default for s in specs}
