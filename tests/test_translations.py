"""Every abort reason in strings.json must have literal text in translations/.

`[%key:common::...%]` references in strings.json are resolved by hassfest only
for core integrations; a custom component without the key in its
translations/*.json shows the raw reason (e.g. `single_instance_allowed`).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

COMPONENT = Path(__file__).parents[1] / "custom_components" / "netatmo_bubendorff"
TRANSLATIONS = sorted((COMPONENT / "translations").glob("*.json"))


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


ABORT_KEYS = sorted(_load(COMPONENT / "strings.json")["config"]["abort"])


def test_translations_found() -> None:
    assert {p.stem for p in TRANSLATIONS} >= {"en", "pl", "de", "fr", "es"}


@pytest.mark.parametrize("path", TRANSLATIONS, ids=lambda p: p.stem)
def test_abort_reasons_translated(path: Path) -> None:
    abort = _load(path).get("config", {}).get("abort", {})

    missing = [key for key in ABORT_KEYS if key not in abort]
    assert not missing, f"{path.name} lacks config.abort: {missing}"
    for key in ABORT_KEYS:
        text = abort[key]
        assert text.strip(), f"{path.name}: empty config.abort.{key}"
        assert "[%key:" not in text, f"{path.name}: unresolved reference in {key}"
