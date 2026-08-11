"""The panel's generated settings forms have a label for every field they draw.

The Mini App builds each module's form from the JSON Schema `/api/meta` ships,
deriving a Fluent key per property: `filters.links` becomes
`setting-filters-links`. Nothing in the TypeScript build checks that key exists —
a missing one renders as the key itself, so a new Pydantic field would appear in
the panel labelled `setting-my-new-flag` and no test would notice.

DECISION: the key derivation is duplicated here rather than imported, because the
authority is the TypeScript in `apps/miniapp/src/settings`. Duplicating it means
this test fails when the two disagree, which is the point; importing a shared
helper would only prove Python agrees with itself.

DECISION: `panel.ftl` is parsed from disk instead of going through `translator`.
The runtime loads `main.ftl` alone — the bot has no use for panel copy — so the
Mini App's own catalogue is only reachable as a file.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from core.registry import registry
from i18n.runtime import LOCALES_DIR, SUPPORTED_LOCALES, translator
from shared.enums import PaymentStatus, Plan, ScheduleKind, TriggerMatch
from shared.plans import Feature

# Fluent identifiers allow underscores, and one key uses one: `plan-white_label`
# is spelled with the enum value verbatim. `test_i18n.py`'s narrower pattern is
# fine for parity checks between two files; here a key that fails to match would
# read as a missing label.
_MESSAGE = re.compile(r"^([a-z][a-z0-9_-]*)\s*=\s*(.+)$", re.MULTILINE)
_LOCALES = tuple(SUPPORTED_LOCALES)


def _panel_keys(locale: str) -> set[str]:
    source = (LOCALES_DIR / locale / "panel.ftl").read_text(encoding="utf-8")
    return {match.group(1) for match in _MESSAGE.finditer(source)}


def _catalogue_keys(locale: str) -> set[str]:
    """Both files the panel merges: it renders bot keys and panel keys alike."""
    main = (LOCALES_DIR / locale / "main.ftl").read_text(encoding="utf-8")
    return _panel_keys(locale) | {match.group(1) for match in _MESSAGE.finditer(main)}


def _deref(schema: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    ref = schema.get("$ref")
    if ref is None:
        return schema
    resolved: dict[str, Any] = defs.get(ref.rsplit("/", 1)[-1], {})
    return resolved


def _unwrap_optional(schema: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any] | None:
    """`T | None` collapses to `T`; any other union has no widget."""
    branches = schema.get("anyOf")
    if branches is None:
        return schema
    real = [branch for branch in branches if branch.get("type") != "null"]
    return _deref(real[0], defs) if len(real) == 1 else None


def _rendered(
    schema: dict[str, Any], defs: dict[str, Any], prefix: str = ""
) -> list[tuple[str, dict[str, Any]]]:
    """Every property the panel's generator draws an input for, with its schema."""
    found: list[tuple[str, dict[str, Any]]] = []
    for name, raw in (schema.get("properties") or {}).items():
        unwrapped = _unwrap_optional(raw, defs)
        if unwrapped is None:
            continue
        prop = _deref(unwrapped, defs)
        path = f"{prefix}.{name}" if prefix else name
        if "enum" in prop or prop.get("type") in {"boolean", "integer", "number", "string"}:
            found.append((path, prop))
        elif prop.get("type") == "array":
            if _deref(prop.get("items", {}), defs).get("type") == "string":
                found.append((path, prop))
            else:
                found.extend(_entry_rows(prop, defs, path))
        elif prop.get("type") == "object" and prop.get("properties"):
            found.extend(_rendered(prop, defs, path))
        elif prop.get("type") == "object":
            found.extend(_map_rows(prop, defs, path))
    return found


# The kinds a repeating group can draw for one of its entries, mirroring
# `ENTRY_KINDS` in `apps/miniapp/src/settings/schema.ts`.
_ENTRY_TYPES = frozenset({"string", "integer", "number"})


def _entry_rows(
    prop: dict[str, Any], defs: dict[str, Any], path: str
) -> list[tuple[str, dict[str, Any]]]:
    """A `list[SomeModel]`, as the label for the list plus one per entry field.

    Only a flat entry qualifies: every field has to be a scalar the group can draw
    inline, so an enum or a nested object anywhere in an entry makes the whole list
    decline — no form, and so no labels to check either.

    The entry fields hang off the list's own key (`setting-greeting-buttons-url`)
    because their names are relative to an entry rather than paths into the config.
    """
    items = _deref(prop.get("items", {}), defs)
    fields: list[tuple[str, dict[str, Any]]] = []
    for name, raw in (items.get("properties") or {}).items():
        unwrapped = _unwrap_optional(raw, defs)
        if unwrapped is None:
            return []
        inner = _deref(unwrapped, defs)
        if "enum" in inner or inner.get("type") not in _ENTRY_TYPES:
            return []
        fields.append((f"{path}.{name}", inner))
    return [(path, prop), *fields] if fields else []


def _map_rows(
    prop: dict[str, Any], defs: dict[str, Any], path: str
) -> list[tuple[str, dict[str, Any]]]:
    """A `dict[K, V]`, as the rows the panel draws for it.

    A closed key set (`dict[SomeEnum, V]`) becomes one row per key, which
    `propertyNames.enum` is what tells the panel. An open-ended `dict[str, str]`
    cannot: the keys are the admin's to invent, so it becomes a pair editor
    instead, labelled by the field and by the two halves of a row.

    A map constrained by neither has no generated form and no labels to check.
    """
    keys = prop.get("propertyNames", {})
    value = prop.get("additionalProperties")
    if not isinstance(value, dict):
        return []
    resolved = _deref(value, defs)
    if (members := keys.get("enum")) is not None:
        return [(f"{path}.{key}", resolved) for key in members]
    if resolved.get("type") == "string" and "pattern" in keys:
        return [(path, prop), (f"{path}.key", keys), (f"{path}.value", resolved)]
    return []


def _all_fields() -> list[tuple[str, dict[str, Any]]]:
    fields: list[tuple[str, dict[str, Any]]] = []
    for spec in registry:
        schema = spec.config_model.model_json_schema()
        fields.extend(_rendered(schema, schema.get("$defs", {})))
    return fields


def _setting_keys() -> set[str]:
    return {"setting-" + path.replace(".", "-").replace("_", "-") for path, _ in _all_fields()}


def _option_keys() -> set[str]:
    return {
        "option-" + value.replace("_", "-")
        for _, prop in _all_fields()
        for value in prop.get("enum", [])
    }


def _hint_keys() -> set[str]:
    """A field constrained by a regex draws `<label>-hint` under itself.

    The panel can state a numeric bound after the fact, once a number falls
    outside it — the input itself suggests what belongs there. A pattern cannot be
    guessed at from an empty box, so the rule is the other way round: wherever the
    schema names one, the form says up front what it wants.
    """
    return {
        "setting-" + path.replace(".", "-").replace("_", "-") + "-hint"
        for path, prop in _all_fields()
        if "pattern" in prop
    }


@pytest.mark.parametrize("locale", _LOCALES)
def test_every_generated_field_has_a_label(locale: str) -> None:
    missing = sorted(_setting_keys() - _panel_keys(locale))
    assert not missing, f"{locale}: settings without a label: {missing}"


@pytest.mark.parametrize("locale", _LOCALES)
def test_every_enum_choice_has_a_label(locale: str) -> None:
    """A dropdown of raw `delete_warn` values is a form nobody can fill in."""
    missing = sorted(_option_keys() - _panel_keys(locale))
    assert not missing, f"{locale}: enum choices without a label: {missing}"


@pytest.mark.parametrize("locale", _LOCALES)
def test_every_patterned_field_says_what_it_wants(locale: str) -> None:
    missing = sorted(_hint_keys() - _panel_keys(locale))
    assert not missing, f"{locale}: patterns with nothing explaining them: {missing}"


@pytest.mark.parametrize("locale", _LOCALES)
def test_every_module_has_a_title_and_description(locale: str) -> None:
    """The chat screen lists modules by these keys before any config loads."""
    t = translator(locale)
    for spec in registry:
        assert t.has(spec.title_key), f"{locale}: missing {spec.title_key}"
        assert t.has(spec.description_key), f"{locale}: missing {spec.description_key}"


@pytest.mark.parametrize("locale", _LOCALES)
def test_every_enum_the_panel_renders_by_name_has_a_label(locale: str) -> None:
    """Screens build these keys from a template literal, so `tsc` cannot see them.

    Each family is a Python enum the panel turns into UI text: a plan badge, a
    payment row, a trigger's match mode, a schedule's kind, a feature in the
    plan comparison. Adding a member to any of them is exactly the change that
    ships a raw `feature-chat-networks` to the screen.

    `plan-` is the one family that keeps the underscore — `plan-white_label`
    predates the panel and the bot renders it too, so the panel appends the enum
    value verbatim rather than fork the bot's catalogue over a hyphen.
    """
    have = _catalogue_keys(locale)
    families = (
        ("plan-", Plan, False),
        ("billing-status-", PaymentStatus, True),
        ("triggers-match-", TriggerMatch, True),
        ("posts-schedule-", ScheduleKind, True),
        ("feature-", Feature, True),
    )
    expected = {
        prefix + (member.value.replace("_", "-") if hyphenate else member.value)
        for prefix, enum, hyphenate in families
        for member in enum
    }
    missing = sorted(expected - have)
    assert not missing, f"{locale}: enum members without a label: {missing}"


def test_no_label_outlives_the_field_it_names() -> None:
    """A stale `setting-*` key is a field that was renamed and half-forgotten.

    Harmless on screen — nothing renders it — but it is also the evidence that
    someone edited the model and only half-followed through, so the next reader
    cannot tell which labels are live.
    """
    stale = sorted(
        {key for key in _panel_keys("ru") if key.startswith("setting-")}
        - _setting_keys()
        - _hint_keys()
    )
    assert not stale, f"labels with no field: {stale}"
