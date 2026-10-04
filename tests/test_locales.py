"""The English and Arabic catalogs must define exactly the same keys."""

import json
from pathlib import Path

LOCALES = Path(__file__).resolve().parent.parent / "locales"


def _keys(locale: str) -> set[str]:
    return set(json.loads((LOCALES / locale / "messages.json").read_text(encoding="utf-8")))


def test_en_and_ar_catalogs_have_identical_keys():
    en, ar = _keys("en"), _keys("ar")
    assert not (en - ar), f"missing in ar: {sorted(en - ar)}"
    assert not (ar - en), f"missing in en: {sorted(ar - en)}"