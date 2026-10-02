"""Language plugins, the registry, and the per-language Profile layout.

Everything language-specific that build_lexicon.py and lexicon.py need is behind one
object per language, `LANGUAGE`, with these callables (CONTRACTS.md section 6):

    script_of(word) -> str                   one of the registry `scripts`, or "mixed"
    tokens(word) -> list[str]                units for composite splitting; [] = never split
    is_content(word) -> bool                 False for bare particles / articles
    lemmas(word) -> list[str]                guarded inflection-reduction candidates
    weight(piece) -> int                     information content (contains tier, stem tier)
    reading_label(record) -> str             reading to show next to the word, "" if none
    name_rating(word, levels) -> str | (str, str) | None
                                             level label for a proper noun; may return
                                             (label, rating_source) to name its method
    normalise(text) -> str                   matching key (casefold etc.)

and one addition the contract did not name, needed so records keep their field names:

    fields(word, entry) -> dict              the record's identity fields from the
                                             dictionary entry: Japanese gives
                                             {"kana", "kanji"}, every other language
                                             {"reading", "headword"}

How the build uses them -- the generic rules live in build_lexicon.py, the plugin only
answers questions about its own script:

    composite  greedy longest match over tokens(word); a single-token piece must have
               weight >= 2 and be is_content(). Pieces join with "" when the tokens
               concatenate back to the word (characters), else with " " (words).
    contains   contiguous runs of tokens(word) (or of characters when tokens is []);
               the piece needs weight >= 3, >= 55% of the word's weight, is_content().
    stem       weight() of the shared leading prefix must reach 2.
    inflection every lemmas() candidate looked up exactly; the lookup also accepts an
               accent-insensitive hit, preferring an accent-exact one (tie-breaker).

Getting a plugin: always through `plugin(code)`. A module may expose `LANGUAGE`
directly (japanese, chinese, korean) or a factory `for_code(code)` (latin, shared by
fr/de/es/it/pt); `plugin()` prefers the factory, so callers never need to know.

Plugin modules import nothing from this package, so a connection's fetcher can load one
straight from its file path.
"""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Profile/data/scripts/languages/ -> the project root is four up.
ROOT = HERE.parents[3]
REGISTRY_FILE = ROOT / "languages.json"
DEFAULT = "ja"

_registry: dict | None = None
_plugins: dict = {}


def registry() -> dict:
    """languages.json without its `_doc` key: code -> spec."""
    global _registry
    if _registry is None:
        data = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
        _registry = {k: v for k, v in data.items() if not k.startswith("_")}
    return _registry


def spec(code: str) -> dict:
    reg = registry()
    if code not in reg:
        raise SystemExit(f"Unknown language {code!r} -- supported: {', '.join(sorted(reg))}")
    return reg[code]


def levels(code: str) -> list[str]:
    """Test levels, easiest first. rating = len(levels) - index."""
    return list(((spec(code).get("tests") or {}).get("levels")) or [])


def rating_of(label: str, order: list[str]) -> int | None:
    return len(order) - order.index(label) if label in order else None


def label_of(rating, order: list[str]) -> str | None:
    """Inverse of rating_of: 5 -> "N5" for Japanese."""
    if not isinstance(rating, int) or not 1 <= rating <= len(order):
        return None
    return order[len(order) - rating]


def plugin(code: str):
    """The LANGUAGE object for a registry code (cached)."""
    if code not in _plugins:
        module = importlib.import_module(f"{__name__}.{spec(code)['plugin']}")
        factory = getattr(module, "for_code", None)
        _plugins[code] = factory(code) if callable(factory) else module.LANGUAGE
    return _plugins[code]


class Levels(dict):
    """form -> level label for every listed expression and reading, plus `order`
    (easiest first). This is what name_rating() receives as `levels`."""

    def __init__(self, order, mapping=()):
        super().__init__(mapping)
        self.order = list(order)

    def index(self, label: str) -> int:
        return self.order.index(label)

    def hardest(self, labels):
        return max(labels, key=self.order.index)

    def easiest(self, labels):
        return min(labels, key=self.order.index)


# ------------------------------------------------------------------ Profile layout
def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except json.JSONDecodeError:
        return {}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def active_code(profile_path: Path, write: bool = True) -> str:
    """The active language from Profile/profile.json["language"].

    Missing -> "ja" (the only language before the registry existed), written back.
    A language *name* ("Japanese", what older builds wrote) is mapped to its code and
    written back. Anything else unknown is an error listing the supported codes.
    """
    data = _read_json(profile_path)
    value = data.get("language")
    reg = registry()
    code = value
    if not value:
        code = DEFAULT
    elif value not in reg:
        by_name = {v["name"].lower(): k for k, v in reg.items()}
        code = by_name.get(str(value).lower())
        if code is None:
            raise SystemExit(f"{profile_path}: language {value!r} is not in languages.json -- "
                             f"supported: {', '.join(sorted(reg))}")
    if code != value and write:
        data["language"] = code
        _write_json(profile_path, data)
    return code


def language_dir(profile_dir: Path, code: str) -> Path:
    return Path(profile_dir) / code


def migrate_flat(profile_dir: Path, code: str) -> list[str]:
    """Move Profile/lexicon.jsonl and names.jsonl into Profile/ja/ (CONTRACTS section 1).

    Only for Japanese -- the flat layout predates every other language -- and only when
    Profile/ja/ does not exist yet, so it can never clobber a per-language lexicon. A
    rename, so the learner's records survive byte for byte. Returns the moved names.
    """
    profile_dir = Path(profile_dir)
    target = profile_dir / DEFAULT
    flat = profile_dir / "lexicon.jsonl"
    if code != DEFAULT or not flat.exists() or target.exists():
        return []
    target.mkdir(parents=True)
    moved = []
    for name in ("lexicon.jsonl", "names.jsonl"):
        src = profile_dir / name
        if src.exists():
            os.replace(src, target / name)
            moved.append(name)
    return moved
