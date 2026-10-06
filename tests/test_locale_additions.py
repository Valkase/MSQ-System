"""The Phase 5 locale additions must be consistent and mergeable."""

import json
from pathlib import Path

import pytest

from scripts.merge_locale_keys import ADDITIONS, merge


def _load(code):
    return json.loads((ADDITIONS / f"phase5_{code}.json").read_text(encoding="utf-8"))


def test_additions_have_identical_keys_in_both_languages():
    assert set(_load("en")) == set(_load("ar"))


def test_merge_adds_new_keys_is_idempotent_and_detects_conflicts(tmp_path):
    catalog = tmp_path / "messages.json"
    catalog.write_text(json.dumps({"existing": "x"}), encoding="utf-8")
    adds = tmp_path / "adds.json"
    adds.write_text(json.dumps({"new.key": "y"}), encoding="utf-8")

    assert merge(catalog, adds) == 1
    assert json.loads(catalog.read_text(encoding="utf-8")) == {"existing": "x", "new.key": "y"}
    assert merge(catalog, adds) == 0  # re-running adds nothing

    adds.write_text(json.dumps({"existing": "DIFFERENT"}), encoding="utf-8")
    with pytest.raises(SystemExit):
        merge(catalog, adds)
