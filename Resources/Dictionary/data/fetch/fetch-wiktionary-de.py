#!/usr/bin/env python3
"""Fetch a German-English dictionary from Wiktionary (via kaikki.org) into Dictionary/German/.

Source: kaikki.org's machine-readable extract of English Wiktionary, German section
(https://kaikki.org/dictionary/German/). Licence CC BY-SA 4.0 / GFDL (Wiktionary).
The dump is streamed and decompressed on the fly -- nothing large touches the disk.

Scope: the whole dump is far bigger than any course needs, so only lemmas that appear
-- as themselves or through any inflected form -- among the 50,000 words
of the OpenSubtitles 2018 list (hermitdave/FrequencyWords, de_50k) are kept, plus
short set phrases made only of such words. --full keeps every lemma in the dump.

Output: German/wiktionary-de.csv  (CONTRACTS §3 dictionary schema)

    headword  the lemma (dictionary form)
    reading   empty -- Latin script is its own reading
    forms     inflected forms and alternative spellings, pipe-separated
              (Haus -> Hauses|Häuser|...; essen -> isst|aß|gegessen|...)
    readings  empty
    pos       n|v|adj|adv|pron|prep|det|conj|int|num|prt|exp|suf|pref|contr
    senses    English glosses, pipe-separated (at most 12)
    common    1 if the lemma or a form of it is among the 10,000 most frequent words

Rows are ordered most frequent first. Entries that are only "inflection of X" or
"alternative form of X" are not rows of their own: they are folded into X's forms.

Usage:
    python fetch-wiktionary-de.py
    python fetch-wiktionary-de.py --full
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import _fetchlib as lib  # noqa: E402

CODE = "de"
FREQ = "de"
SOURCE = "wiktionary-de"


def output() -> Path:
    return lib.dictionary_dir(CODE) / f"{SOURCE}.csv"


def fetch(full: bool = False) -> None:
    timer = lib.Timer()
    rows, stats = lib.latin_dictionary(lib.language(CODE)["name"], FREQ, full)
    if len(rows) < 1_000:
        raise lib.FetchError(f"only {len(rows)} lemmas parsed -- kaikki format changed?")
    path = output()
    n = lib.write_csv(path, lib.DICTIONARY_COLUMNS, rows)
    common = sum(r["common"] == "1" for r in rows)
    print(f"  {stats['entries']:,} Wiktionary entries read, {stats['lemmas']:,} lemmas")
    print(f"wrote {lib.rel(path)}: {n:,} rows ({common:,} common), "
          f"{path.stat().st_size / 1024 / 1024:.1f} MB in {timer}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--full", action="store_true", help="keep every lemma, not just the frequent ones")
    args = ap.parse_args()
    fetch(args.full)


if __name__ == "__main__":
    lib.run(main)
