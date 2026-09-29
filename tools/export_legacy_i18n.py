"""One-shot export of the legacy translation catalog into JSON resources.

Reads ``localization.TRANSLATIONS`` from the pinned legacy commit (never the working tree) and
writes ``src/resources/i18n/<lang>.json`` plus a golden key list used by the i18n parity test.
After the cutover the JSON files are hand-maintained and this tool is only kept for history.
"""

import json
from pathlib import Path

from tools.legacy_oracle import LegacyOracle, extract

ROOT = Path(__file__).absolute().parent.parent
I18N_DIR = ROOT / "src" / "resources" / "i18n"
GOLDEN = ROOT / "tests" / "golden" / "i18n" / "legacy_keys.json"


def export() -> dict[str, int]:
    oracle = LegacyOracle(extract())
    loc = oracle.module("localization")
    translations: dict[str, dict[str, str]] = loc.TRANSLATIONS
    I18N_DIR.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    for lang, catalog in translations.items():
        target = I18N_DIR / f"{lang}.json"
        existing: dict[str, str] = {}
        if target.is_file():
            existing = json.loads(target.read_text("utf-8"))
        merged = {**existing, **{key: catalog[key] for key in sorted(catalog)}}
        target.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", "utf-8")
        counts[lang] = len(catalog)
    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    golden = {
        "languages": sorted(translations),
        "keys": sorted(translations["en"]),
        "category_keys": dict(loc.CATEGORY_TRANSLATION_KEYS),
        "view_mode_keys": dict(loc.VIEW_MODE_TRANSLATION_KEYS),
    }
    GOLDEN.write_text(json.dumps(golden, ensure_ascii=False, indent=2) + "\n", "utf-8")
    return counts


def main() -> int:
    for lang, count in export().items():
        print(f"{lang}: {count} keys")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
