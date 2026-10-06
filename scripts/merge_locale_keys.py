"""
Merge the Phase 5 message keys into locales/en and locales/ar.

    python -m scripts.merge_locale_keys

Safe to re-run (existing identical keys are skipped; a key that already exists
with a DIFFERENT text aborts). NOTE: the catalogs are rewritten with uniform
2-space indentation, so expect some whitespace-only diff noise the first time.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ADDITIONS = ROOT / "scripts" / "locale_additions"


def merge(catalog_path: Path, additions_path: Path) -> int:
    """Merge additions into the catalog file. Returns how many keys were added."""
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    additions = json.loads(additions_path.read_text(encoding="utf-8"))

    conflicts = [k for k, v in additions.items() if k in catalog and catalog[k] != v]
    if conflicts:
        raise SystemExit(f"{catalog_path}: keys already exist with different text: {conflicts}")

    new = {k: v for k, v in additions.items() if k not in catalog}
    catalog.update(new)
    catalog_path.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return len(new)


def main() -> int:
    for code in ("en", "ar"):
        added = merge(ROOT / "locales" / code / "messages.json", ADDITIONS / f"phase5_{code}.json")
        print(f"locales/{code}/messages.json: {added} key(s) added")
    return 0


if __name__ == "__main__":
    sys.exit(main())
