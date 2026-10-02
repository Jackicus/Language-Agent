#!/usr/bin/env python3
"""Fetch the HSK 2.0 vocabulary lists into Tests/Chinese/.

Source: drkameleon/complete-hsk-vocabulary (MIT; meanings from CC-CEDICT), which merges
the HSK 2.0 lists (clem109/hsk-vocabulary) and the HSK 3.0 lists (elkmovie/hsk30) into
one file with pinyin, traditional forms and English meanings per word.

Why HSK 2.0: the registry has six levels HSK1..HSK6, which is exactly HSK 2.0 (2009-
2021, 4,991 words, still the version most courses and the Duolingo tree align with).
HSK 3.0 has nine levels with 7-9 merged into one band and ~11,000 words; mapping it onto
six labels would be invention. Each row's HSK 3.0 level is kept in `tags` instead, so
nothing is lost. Words that are only in HSK 3.0 are not written -- they are not in the
exam the labels name.

A word listed at several HSK 2.0 levels takes the lowest.

Output: Chinese/hsk-1.csv ... hsk-6.csv

    level        HSK1..HSK6
    expression   simplified hanzi
    reading      pinyin with tone marks, syllables space-separated (xiè xie)
    meaning      English senses, `; `-separated
    tags         hsk2.0, plus hsk3.0-N (N = 1..6 or 7-9) when the word is in HSK 3.0

Usage:
    python fetch-hsk.py            # all six levels
    python fetch-hsk.py 1 2        # or HSK1 HSK2
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import _fetchlib as lib  # noqa: E402

CODE = "zh"
SOURCE = "hsk"
URL = "https://raw.githubusercontent.com/drkameleon/complete-hsk-vocabulary/main/complete.min.json"


def load() -> list[dict]:
    data = json.loads(lib.get(URL))
    if not isinstance(data, list) or len(data) < 5_000:
        raise lib.FetchError("complete.min.json is not the expected word array -- source changed?")
    return data


def primary_forms(word: dict) -> list[dict]:
    """Drop surname and variant-only readings when the word has a real one."""
    forms = word.get("f", [])
    real = [f for f in forms if f.get("i", {}).get("y", "")[:1].islower()
            and not all(m.lower().startswith(("surname", "variant of", "old variant of")) for m in f.get("m", []))]
    return real or forms


def rows_by_level(data: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for word in data:
        levels = word.get("l", [])
        old = sorted(int(l[1:]) for l in levels if l.startswith("o") and l[1:].isdigit())
        if not old:
            continue
        new = sorted(int(l[1:]) for l in levels if l.startswith("n") and l[1:].isdigit())
        forms = primary_forms(word)
        meanings = list(dict.fromkeys(m for f in forms for m in f.get("m", [])))
        tags = ["hsk2.0"]
        if new:
            tags.append(f"hsk3.0-{'7-9' if new[0] >= 7 else new[0]}")
        level = f"HSK{old[0]}"
        out.setdefault(level, []).append({
            "level": level,
            "expression": word["s"],
            "reading": forms[0].get("i", {}).get("y", "") if forms else "",
            "meaning": "; ".join(meanings[:8]),
            "tags": " ".join(tags),
        })
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("levels", nargs="*", help="levels to write, e.g. 1 2 or HSK1 (default: all)")
    args = ap.parse_args()
    levels = lib.language(CODE)["tests"]["levels"]
    wanted = [a.upper() if a.upper().startswith("HSK") else f"HSK{a}" for a in args.levels] or levels
    bad = [w for w in wanted if w not in levels]
    if bad:
        raise lib.FetchError(f"unknown level(s) {bad} -- expected any of {levels}")

    timer = lib.Timer()
    by_level = rows_by_level(load())
    total = 0
    for level in wanted:
        path = lib.tests_dir(CODE) / lib.level_filename(SOURCE, level)
        n = lib.write_csv(path, lib.TEST_COLUMNS, by_level.get(level, []))
        total += n
        print(f"  {level}: {n:,} words -> {lib.rel(path)}")
    print(f"{total:,} words across {len(wanted)} level(s) in {timer}")


if __name__ == "__main__":
    lib.run(main)
