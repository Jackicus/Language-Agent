"""Shared fixtures: path shim, tiny hand-built test-list and dictionary rows, and sandboxing.

Nothing here touches the real Profile/, Connections/ or Resources/ trees. Scripts are
imported (which only computes path constants) and every Path-valued module global that
points inside the real project is remapped into a temporary directory before any code
that reads or writes files is called.
"""

from __future__ import annotations

import sys

# Importing the scripts must not drop __pycache__/ into Profile/data/scripts/.
sys.dont_write_bytecode = True
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
SCRIPTS = PROJECT / "Profile" / "data" / "scripts"
for p in (str(SCRIPTS), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)


TEST_COLUMNS = ["level", "expression", "reading", "meaning", "tags"]
DICTIONARY_COLUMNS = ["headword", "reading", "forms", "readings", "pos", "senses", "common"]
JA_LEVELS = ["N5", "N4", "N3", "N2", "N1"]
CEFR = ["A1", "A2", "B1", "B2", "C1", "C2"]


def jlpt(level: str, expression: str, reading: str, meaning: str) -> dict:
    """One row of Resources/Tests/<Language>/<source>-<level>.csv (any language)."""
    return {"level": level, "expression": expression, "reading": reading, "meaning": meaning, "tags": ""}


test_row = jlpt


def jmdict(kanji: str, kana: str, kanji_all: str | None = None, kana_all: str | None = None,
           pos: str = "n", senses: str = "", common: str = "1") -> dict:
    """One JMdict entry in the generic dictionary schema (CONTRACTS section 3).

    Takes JMdict's own terms -- kanji spelling ("" if kana-only) and kana reading -- and
    maps them as fetch-jmdict.py does: headword = kanji or kana, forms = kanji spellings.
    """
    kanji_all = kanji if kanji_all is None else kanji_all
    kana_all = kana if kana_all is None else kana_all
    return {"headword": kanji or kana, "reading": kana, "forms": kanji_all, "readings": kana_all,
            "pos": pos, "senses": senses, "common": common}


def entry(headword: str, reading: str = "", forms: str = "", readings: str = "",
          pos: str = "n", senses: str = "", common: str = "1") -> dict:
    """One generic dictionary row, for languages other than Japanese."""
    return {"headword": headword, "reading": reading, "forms": forms, "readings": readings,
            "pos": pos, "senses": senses, "common": common}


def plugin(code: str = "ja"):
    import languages
    return languages.plugin(code)


def grader(tests: list[dict], code: str = "ja", levels: list[str] | None = None):
    """build_lexicon.Grader for a registry language (Japanese by default)."""
    import build_lexicon
    import languages
    return build_lexicon.Grader(tests, languages.plugin(code), levels or languages.levels(code))


def sandbox(module, tmp: Path) -> ExitStack:
    """Remap every Path global of `module` into `tmp`.

    Paths inside the project keep their relative layout (Profile/lexicon.jsonl lands at
    tmp/Profile/lexicon.jsonl). Paths outside it -- e.g. lexicon.py's LEXICON_DIR env
    override pointing somewhere else at import time -- go under tmp/_ext/ with their
    absolute layout, so LEXICON still sits inside PROFILE_DIR. Generic on purpose: a
    newly added path constant is redirected too instead of naming real data.
    """
    stack = ExitStack()
    real = PROJECT.resolve()
    for name, value in list(vars(module).items()):
        if not isinstance(value, Path):
            continue
        resolved = value.resolve()
        try:
            target = tmp / resolved.relative_to(real)
        except ValueError:
            target = tmp / "_ext" / resolved.relative_to(resolved.anchor)
        stack.enter_context(mock.patch.object(module, name, target))
    return stack


def assert_sandboxed(testcase, module, tmp: Path) -> None:
    """Refuse to go on unless every Path global of `module` sits inside `tmp`."""
    tmp = tmp.resolve()
    for name, value in vars(module).items():
        if isinstance(value, Path):
            resolved = value.resolve()
            if resolved != tmp and tmp not in resolved.parents:
                testcase.fail(f"{module.__name__}.{name} is not sandboxed: {value}")
