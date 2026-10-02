#!/usr/bin/env python3
"""Scrape a whole Duolingo course vocabulary into a table, one row per word.

duome's "by skill" vocabulary page lists every word a course teaches, in course order,
grouped under the unit that introduces it. That unit number is the useful column: it
turns "which words does the learner have" into a single comparison against their
current unit, with no per-word tracking needed.

The page is course-level, not account-level, so any course duome serves can be fetched
whether or not this account studies it.

Output: data/languages/<FromName>/<languagename>.csv   (names from languages.json)
        e.g. en -> ja lands at data/languages/English/japanese.csv

    unit          the unit that FIRST introduces the word
    unit_name     e.g. "Basics"
    unit_topic    e.g. "Order food and drinks"
    position      order within that unit
    word          as written
    reading       whatever duome shows in brackets after the word (romaji, pinyin,
                  romanised hangul), empty when it shows none -- e.g. kanji-only
                  Japanese entries and every Latin-script course
    gloss         English senses, pipe-separated
    script        from the language plugin's script_of, else latin | mixed | a registry script
    repeat_units  later units that re-introduce the word, pipe-separated
    audio         pronunciation clip URL
    seen          always empty: Duolingo gates by unit, not by per-card evidence

Usage:
    python fetch-word-lists.py            # the active course in profile.json, else en ja
    python fetch-word-lists.py fr         # en -> fr
    python fetch-word-lists.py en ja
    python fetch-word-lists.py en zs      # duome's code for Mandarin is zs; `zh` is accepted too
"""

from __future__ import annotations

import csv
import re
import sys
import urllib.error

import _common as duome

# <div class="path-section-delimiter">...<span title="hash">12 <span class="small-label">Family</span> Talk about relatives</span>
UNIT_RE = re.compile(
    r'<div class="path-section-delimiter">.*?<span title="[^"]*">\s*'
    r"(\d+)\s*<span class=\"small-label\">(.*?)</span>\s*(.*?)\s*</span>",
    re.S,
)

# A word row. The bracketed reading span is optional: Latin-script courses never have
# one, and Japanese kanji-only entries (東京, 私) omit it. Its content is taken verbatim.
WORD_RE = re.compile(
    r'(?:<div class="playback[^"]*"\s+data-src="([^"]*)"></div>\s*)?'
    r'<span class="_blue\s+wA">(.*?)</span>\s*'
    r'(?:<span class="cCCC">\s*-\s*\[(.*?)\]</span>\s*)?'
    r'<span class="cCCC wT">\s*-\s*(.*?)</span>',
    re.S,
)

COLUMNS = ["unit", "unit_name", "unit_topic", "position", "word", "reading", "gloss", "script", "repeat_units", "audio", "seen"]


def parse(html: str, script_of) -> list[dict]:
    marks = [(m.start(), int(m.group(1)), duome.clean(m.group(2)), duome.clean(m.group(3))) for m in UNIT_RE.finditer(html)]
    if not marks:
        raise SystemExit("No unit headers found -- duome's vocabulary markup has changed, or it does not serve this course.")

    rows: dict[str, dict] = {}
    spans = [(m, marks[i + 1][0] if i + 1 < len(marks) else len(html)) for i, m in enumerate(marks)]

    for (offset, number, name, topic), end in spans:
        position = 0
        for match in WORD_RE.finditer(html, offset, end):
            audio, word, reading, glosses = match.groups()
            word = duome.clean(word)
            if not word:
                continue
            if word in rows:
                # Already introduced earlier; just note that this unit revisits it.
                if number != rows[word]["unit"] and number not in rows[word]["repeat_units"]:
                    rows[word]["repeat_units"].append(number)
                continue
            position += 1
            rows[word] = {
                "unit": number,
                "unit_name": name,
                "unit_topic": topic,
                "position": position,
                "word": word,
                "reading": duome.clean(reading) if reading else "",
                "gloss": "|".join(g.strip() for g in duome.clean(glosses).split(",") if g.strip()),
                "script": script_of(word),
                "repeat_units": [],
                "audio": audio or "",
                "seen": "",
            }
    return sorted(rows.values(), key=lambda r: (r["unit"], r["position"]))


def main() -> None:
    args = sys.argv[1:]
    if args and args[0] in ("-h", "--help"):
        print(__doc__)
        return
    if len(args) == 0:
        src, dst = duome.active_course() or ("en", "ja")
    elif len(args) == 1:
        src, dst = "en", args[0]          # one arg is the language being learned
    elif len(args) == 2:
        src, dst = args
    else:
        raise SystemExit("usage: fetch-word-lists.py [from] <to>   e.g. en ja")

    code = duome.duome_code(dst)          # registry key (zh) -> duome course code
    try:
        html = duome.get(f"/vocabulary/{src}/{code}/skills")
    except (urllib.error.URLError, OSError) as exc:
        raise SystemExit(f"Could not reach duome.eu for {src}-{code}: {exc}")

    script_of, classifier = duome.script_classifier(code)
    rows = parse(html, script_of)

    # Grouped by the language you learn FROM, since one base language fans out to many
    # courses: languages/English/japanese.csv, languages/English/korean.csv, ...
    out = duome.wordlist_path(src, code)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({**row, "repeat_units": "|".join(str(u) for u in row["repeat_units"])})

    units = sorted({r["unit"] for r in rows})
    scripts: dict[str, int] = {}
    for r in rows:
        scripts[r["script"]] = scripts.get(r["script"], 0) + 1
    repeats = sum(len(r["repeat_units"]) for r in rows)
    readings = sum(1 for r in rows if r["reading"])

    print(f"{src} -> {code} ({duome.lang_name(src)} -> {duome.lang_name(code)})")
    print(f"  {len(rows)} unique words across {len(units)} units (unit {units[0]}-{units[-1]})")
    print(f"  {repeats} later re-introductions, {sum(1 for r in rows if r['audio'])} with audio, {readings} with a reading")
    print(f"  by script ({classifier}): " + ", ".join(f"{k}={v}" for k, v in sorted(scripts.items(), key=lambda kv: -kv[1])))
    print(f"wrote {out.relative_to(duome.PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
