#!/usr/bin/env python3
"""Build TOPIK vocabulary lists into Tests/Korean/.

Source: julienshim/combined_korean_vocabulary_list (MIT), which merges two official
lists into one TSV:

  - TOPIK 어휘 목록 공개 목록 (2015), published by NIIED/TOPIK -- 5,992 entries graded
    only 초급 (beginner, TOPIK I) and 중급 (intermediate and up, TOPIK II)
  - 한국어 학습용 어휘 목록 (2003), National Institute of Korean Language -- ~6,000
    learner words graded A/B/C and ranked by frequency

Only words on the TOPIK list are written; NIKL is used to order them. NIKL-only words
are not TOPIK vocabulary and are left out (they still mark `common` in the dictionary).

The published list has two bands; the registry has six levels. The split is ours and is
tagged `level-split` so it can be told apart from the published grading:

  TOPIK1/TOPIK2   the 초급 band, halved
  TOPIK3..TOPIK6  the 중급 band, quartered

Within a band, words are ordered by NIKL grade (A, B, C, then not in NIKL), then NIKL
frequency rank -- so easier, more frequent words land in the lower level.

`meaning` comes from the Wiktionary dictionary (Dictionary/Korean/wiktionary-ko.csv,
fetched first if missing): the published list carries no English. Homographs are told
apart by the list's hanja (가구 家具 "furniture" vs 家口 "household") and then by part of
speech. Words with no English gloss are dropped and counted.

Output: Korean/topik-1.csv ... topik-6.csv

    level        TOPIK1..TOPIK6
    expression   hangul (homograph numbers stripped: 가구03 -> 가구)
    reading      Revised Romanisation from the dictionary
    meaning      English senses, `; `-separated
    tags         topik-beginner|topik-intermediate, nikl-a|b|c when graded, level-split

Usage:
    python fetch-topik.py            # all six levels
    python fetch-topik.py 1 2        # or TOPIK1 TOPIK2
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import _fetchlib as lib  # noqa: E402
import _korean  # noqa: E402

CODE = "ko"
SOURCE = "topik"
DICTIONARY_FETCHER = lib.RESOURCES / "Dictionary" / "data" / "fetch" / "fetch-wiktionary-ko.py"
BANDS = {"초급": ("beginner", ["TOPIK1", "TOPIK2"]),
         "중급": ("intermediate", ["TOPIK3", "TOPIK4", "TOPIK5", "TOPIK6"])}


def run_dictionary() -> None:
    spec = importlib.util.spec_from_file_location("dictionary_fetcher", DICTIONARY_FETCHER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.fetch()


def gloss(word: str, hanja: str, pos: str, index: dict[str, list[dict]]) -> dict | None:
    rows = index.get(word, [])
    if hanja:
        rows = [r for r in rows if hanja in r["forms"].split("|")] or rows
    tag = _korean.POS.get(pos)
    if tag:
        rows = [r for r in rows if tag in r["pos"].split("|")] or rows
    return rows[0] if rows else None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("levels", nargs="*", help="levels to write, e.g. 1 2 or TOPIK1 (default: all)")
    args = ap.parse_args()
    levels = lib.language(CODE)["tests"]["levels"]
    wanted = [a.upper() if a.upper().startswith("TOPIK") else f"TOPIK{a}" for a in args.levels] or levels
    bad = [w for w in wanted if w not in levels]
    if bad:
        raise lib.FetchError(f"unknown level(s) {bad} -- expected any of {levels}")
    timer = lib.Timer()

    dictionary = lib.dictionary_dir(CODE) / "wiktionary-ko.csv"
    if not dictionary.exists():
        print(f"{lib.rel(dictionary)} missing -- fetching the dictionary first")
        run_dictionary()
    index: dict[str, list[dict]] = {}
    for row in lib.read_csv(dictionary):
        index.setdefault(row["headword"], []).append(row)

    # One entry per (word, hanja); a word listed in both bands takes the easier one.
    words: dict[tuple[str, str], dict] = {}
    for row in _korean.load():
        band = row["topik_level"]
        if band not in BANDS:
            continue
        key = (row["word"], row["hanja"])
        grade = row["nikl_level"] or "Z"
        rank = int(row["rank"]) if row["rank"].isdigit() else 10**6
        sort = (list(BANDS).index(band), grade, rank)
        if key not in words or sort < words[key]["sort"]:
            words[key] = {"row": row, "band": band, "sort": sort}

    by_band: dict[str, list[dict]] = {b: [] for b in BANDS}
    for item in sorted(words.values(), key=lambda w: w["sort"]):
        by_band[item["band"]].append(item)

    out: dict[str, list[dict]] = {}
    dropped = 0
    for band, (name, labels) in BANDS.items():
        items = by_band[band]
        size = -(-len(items) // len(labels))  # ceil: earlier levels take the remainder
        for i, item in enumerate(items):
            level = labels[min(i // size, len(labels) - 1)]
            row = item["row"]
            entry = gloss(row["word"], row["hanja"], row["part_of_speech"], index)
            if entry is None or not entry["senses"]:
                dropped += 1
                continue
            tags = [f"topik-{name}"]
            if row["nikl_level"]:
                tags.append(f"nikl-{row['nikl_level'].lower()}")
            tags.append("level-split")
            out.setdefault(level, []).append({
                "level": level,
                "expression": row["word"],
                "reading": entry["reading"],
                "meaning": "; ".join(entry["senses"].split("|")[:6]),
                "tags": " ".join(tags),
            })

    total = 0
    for level in wanted:
        path = lib.tests_dir(CODE) / lib.level_filename(SOURCE, level)
        n = lib.write_csv(path, lib.TEST_COLUMNS, out.get(level, []))
        total += n
        print(f"  {level}: {n:,} words -> {lib.rel(path)}")
    print(f"{total:,} words across {len(wanted)} level(s); "
          f"{dropped:,} of {len(words):,} TOPIK words had no English gloss and were dropped ({timer})")


if __name__ == "__main__":
    lib.run(main)
