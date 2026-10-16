"""Phase 6 (English/Arabic): every key the code uses exists in BOTH catalogs, with matching placeholders."""

import ast
import json
import re
import string
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAMESPACES = (
    "gui", "fields", "validation", "permissions", "auth", "users",
    "patients", "doctors", "transactions", "attachments", "adjustments", "dates",
)
KEY_RE = re.compile(r"^(%s)(\.[a-z0-9_]+)+$" % "|".join(NAMESPACES))

# Keys built dynamically in the code (f-strings), listed explicitly.
DYNAMIC_KEYS = (
    ["gui.role.admin", "gui.role.receptionist"]
    + [f"gui.history.col_{c}" for c in ("date", "by", "action", "field", "old", "new")]
    + [f"gui.history.action_{a}" for a in ("created", "edited", "deleted")]
    + [
        f"gui.transactions.col_{c}"
        for c in ("date", "patient", "doctor", "total", "doctor_share", "center_share", "description")
    ]
    + [f"gui.update.failed_{k}" for k in ("download", "verify", "apply")]
)


def _catalog(code: str) -> dict:
    return json.loads((ROOT / "locales" / code / "messages.json").read_text(encoding="utf-8"))

def _keys_used_in_code() -> set[str]:
    used = set()
    for folder in ("gui", "logic"):
        for path in (ROOT / folder).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    value = node.value
                    # Skip prefixes of dynamically built keys, e.g. the
                    # "gui.history.col_" part of f"gui.history.col_{c}".
                    # Those full keys are listed explicitly in DYNAMIC_KEYS.
                    if value.endswith(("_", ".")):
                        continue
                    if KEY_RE.match(value):
                        used.add(value)
    return used


def _placeholders(template: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


def test_every_key_used_in_code_exists_in_both_languages():
    used = _keys_used_in_code() | set(DYNAMIC_KEYS)
    for code in ("en", "ar"):
        missing = sorted(k for k in used if k not in _catalog(code))
        assert missing == [], f"keys used in code but missing from locales/{code}: {missing}"


def test_english_and_arabic_use_the_same_placeholders():
    en, ar = _catalog("en"), _catalog("ar")
    mismatched = {
        k: (sorted(_placeholders(en[k])), sorted(_placeholders(ar[k])))
        for k in en
        if k in ar and _placeholders(en[k]) != _placeholders(ar[k])
    }
    assert mismatched == {}


def test_no_catalog_value_is_empty():
    for code in ("en", "ar"):
        empty = [k for k, v in _catalog(code).items() if not str(v).strip()]
        assert empty == []