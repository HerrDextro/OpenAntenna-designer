"""Registry of antenna templates."""

from __future__ import annotations

from .base import AntennaTemplate

_TEMPLATES: dict[str, AntennaTemplate] = {}


def _register(template: AntennaTemplate) -> None:
    _TEMPLATES[template.id] = template


def get_template(template_id: str) -> AntennaTemplate:
    if not _TEMPLATES:
        _load()
    try:
        return _TEMPLATES[template_id]
    except KeyError:
        raise KeyError(f"unknown antenna template {template_id!r}") from None


def all_templates() -> list[AntennaTemplate]:
    if not _TEMPLATES:
        _load()
    return list(_TEMPLATES.values())


def _load() -> None:
    from .monopole import MonopoleTemplate

    _register(MonopoleTemplate())
