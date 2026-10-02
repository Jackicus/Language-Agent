#!/usr/bin/env python3
"""Build German CEFR-labelled frequency bands into Tests/German/.

There is no official CEFR vocabulary list for German. This is an approximation and is
labelled as one: `tags` is `frequency-band` on every row and languages.json says
`official: false`, so nothing downstream should read these levels as exam syllabi.

The Goethe-Institut A1/A2/B1 lists were considered and not used: they are
(c) Goethe-Institut, published only as PDFs, and the GitHub transcriptions are
unlicensed, per-level, and from different hands. See Resources/README.md.

Method:
  1. Take the OpenSubtitles 2018 frequency list (hermitdave/FrequencyWords,
     de_50k, CC BY-SA 4.0) -- 50,000 word forms, most frequent first.
  2. Map each word form to lemmas through the Wiktionary dictionary
     (Dictionary/German/wiktionary-de.csv; fetched first if missing). A form that
     spells a lemma counts for it; otherwise it counts for the lemma it inflects, and
     when several claim it, only the one whose own spelling is most frequent ("suis"
     -> être, not suivre). Homographs therefore take their spelling's frequency:
     French est ("east") lands in A1 because "est" (is) is frequent. Outside German, a casefolded form
     prefers the lowercase lemma (são, not São). A lemma's rank is its best form's.
  3. Forms with no dictionary entry (names, English, fragments) are dropped and
     counted. `meaning` is the lemma's first six English senses.
  4. Cut the ranked lemmas into six bands, cumulative:
        A1  1-500      A2  501-1,500    B1  1,501-3,500
        B2  3,501-6,500   C1  6,501-11,500   C2  11,501-end

Output: German/freq-de-a1.csv ... freq-de-c2.csv
    level, expression, reading (empty), meaning, tags (frequency-band)

Usage:
    python fetch-freq-de.py            # all six levels
    python fetch-freq-de.py a1 a2
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import _fetchlib as lib  # noqa: E402

CODE = "de"
FREQ = "de"
SOURCE = "freq-de"
DICTIONARY_FETCHER = lib.RESOURCES / "Dictionary" / "data" / "fetch" / "fetch-wiktionary-de.py"


def run_dictionary() -> None:
    spec = importlib.util.spec_from_file_location("dictionary_fetcher", DICTIONARY_FETCHER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.fetch()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("levels", nargs="*", help="levels to write (default: all)")
    args = ap.parse_args()
    timer = lib.Timer()
    dictionary = lib.dictionary_dir(CODE) / "wiktionary-de.csv"
    lib.frequency_bands(CODE, SOURCE, FREQ, dictionary, run_dictionary, args.levels)
    print(f"done in {timer}")


if __name__ == "__main__":
    lib.run(main)
