#!/usr/bin/env python3
"""Fetch JLPT vocabulary lists into Connections/Tests/Japanese/.

The JLPT has no official published vocabulary list -- JEES stopped releasing one after
the 2010 revision. What everyone uses instead are the community reconstructions derived
from the pre-2010 official lists plus analysis of past papers. This pulls from
open-anki-jlpt-decks, which is maintained, sourced from tanos.co.uk, and already
normalised into CSV.

Treat these as a good approximation of each level's expected vocabulary, not as an
authoritative syllabus.

Output: Japanese/jlpt-n5.csv ... jlpt-n1.csv

    level        N5..N1
    expression   the word as written
    reading      kana reading
    meaning      English senses
    tags         the source's own tags (curriculum, old 4-level JLPT grades)

Usage:
    python fetch-jlpt.py            # all five levels
    python fetch-jlpt.py n5 n4
"""

from __future__ import annotations

import csv
import io
import sys
import urllib.request
from pathlib import Path

SOURCE = "https://raw.githubusercontent.com/jamsinclair/open-anki-jlpt-decks/main/src/{level}.csv"
LEVELS = ["n5", "n4", "n3", "n2", "n1"]

HERE = Path(__file__).resolve().parent
CONNECTION_ROOT = HERE.parent.parent
OUT_DIR = CONNECTION_ROOT / "Japanese"
COLUMNS = ["level", "expression", "reading", "meaning", "tags"]


def fetch(level: str) -> list[dict]:
    req = urllib.request.Request(SOURCE.format(level=level), headers={"User-Agent": "Language-Agent/1.0"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        text = resp.read().decode("utf-8", errors="replace")

    rows = []
    for row in csv.DictReader(io.StringIO(text)):
        expression = (row.get("expression") or "").strip()
        if not expression:
            continue
        rows.append(
            {
                "level": level.upper(),
                "expression": expression,
                "reading": (row.get("reading") or "").strip(),
                "meaning": (row.get("meaning") or "").strip(),
                # The source's guid is an Anki artefact -- no use to us, so it is dropped.
                "tags": (row.get("tags") or "").strip(),
            }
        )
    return rows


def main() -> None:
    if {"-h", "--help"} & set(sys.argv[1:]):
        print(__doc__.strip())
        return
    wanted = [a.lower() for a in sys.argv[1:]] or LEVELS
    unknown = [level for level in wanted if level not in LEVELS]
    if unknown:
        raise SystemExit(f"unknown level(s) {unknown} -- expected any of {LEVELS}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    total = 0
    for level in wanted:
        rows = fetch(level)
        out = OUT_DIR / f"jlpt-{level}.csv"
        with out.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        total += len(rows)
        print(f"  {level.upper()}: {len(rows):,} words -> {out.relative_to(CONNECTION_ROOT.parent.parent)}")

    print(f"{total:,} words across {len(wanted)} level(s)")


if __name__ == "__main__":
    main()
