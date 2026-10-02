#!/usr/bin/env python3
"""Scrape a whole Duolingo course vocabulary into a table, one row per word.

duome's "by skill" vocabulary page lists every word a course teaches, in course order,
grouped under the unit that introduces it. That unit number is the useful column: it
turns "which words does the learner have" into a single comparison against their
current unit, with no per-word tracking needed.

Output: data/languages/<FromLanguage>/<targetlanguage>.csv
        e.g. en -> ja lands at data/languages/English/japanese.csv

    unit          the unit that FIRST introduces the word
    unit_name     e.g. "Basics"
    unit_topic    e.g. "Order food and drinks"
    position      order within that unit
    word          as written (kana, kanji, or mixed)
    reading       romaji, where duome supplies one
    gloss         English senses, pipe-separated
    script        hiragana | katakana | kanji | mixed | other
    repeat_units  later units that re-introduce the word, pipe-separated
    audio         pronunciation clip URL

Usage:
    python fetch-word-lists.py            # en -> ja
    python fetch-word-lists.py en ja
    python fetch-word-lists.py en es
"""

from __future__ import annotations

import csv
import re
import sys
import unicodedata

import _common as duome

# <div class="path-section-delimiter">...<span title="hash">12 <span class="small-label">Family</span> Talk about relatives</span>
UNIT_RE = re.compile(
    r'<div class="path-section-delimiter">.*?<span title="[^"]*">\s*'
    r"(\d+)\s*<span class=\"small-label\">(.*?)</span>\s*(.*?)\s*</span>",
    re.S,
)

# A word row. The [romaji] span is absent on kanji-only entries (東京, 私), so it is optional.
WORD_RE = re.compile(
    r'(?:<div class="playback[^"]*"\s+data-src="([^"]*)"></div>\s*)?'
    r'<span class="_blue\s+wA">(.*?)</span>\s*'
    r'(?:<span class="cCCC">\s*-\s*\[(.*?)\]</span>\s*)?'
    r'<span class="cCCC wT">\s*-\s*(.*?)</span>',
    re.S,
)

COLUMNS = ["unit", "unit_name", "unit_topic", "position", "word", "reading", "gloss", "script", "repeat_units", "audio"]


def script_of(word: str) -> str:
    """Classify a token so downstream tools can filter by writing system."""
    kinds = set()
    for ch in word:
        name = unicodedata.name(ch, "")
        if "CJK UNIFIED" in name:
            kinds.add("kanji")
        elif "HIRAGANA" in name:
            kinds.add("hiragana")
        elif "KATAKANA" in name:
            kinds.add("katakana")
    if not kinds:
        return "other"
    return kinds.pop() if len(kinds) == 1 else "mixed"


def parse(html: str) -> list[dict]:
    marks = [(m.start(), int(m.group(1)), duome.clean(m.group(2)), duome.clean(m.group(3))) for m in UNIT_RE.finditer(html)]
    if not marks:
        raise SystemExit("No unit headers found -- duome's vocabulary markup has changed.")

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
            }
    return sorted(rows.values(), key=lambda r: (r["unit"], r["position"]))


def main() -> None:
    args = sys.argv[1:]
    if len(args) == 0:
        src, dst = "en", "ja"
    elif len(args) == 1:
        src, dst = "en", args[0]          # one arg is the language being learned
    elif len(args) == 2:
        src, dst = args
    else:
        raise SystemExit("usage: fetch-word-lists.py [from] <to>   e.g. en ja")

    html = duome.get(f"/vocabulary/{src}/{dst}/skills")
    rows = parse(html)

    # Grouped by the language you learn FROM, since one base language fans out to many
    # courses: languages/English/japanese.csv, languages/English/korean.csv, ...
    from_language = duome.lang_name(src)
    language = duome.lang_name(dst)
    out = duome.LANGUAGES / from_language / f"{language.lower()}.csv"
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

    print(f"{src} -> {dst} ({from_language} -> {language})")
    print(f"  {len(rows)} unique words across {len(units)} units (unit {units[0]}-{units[-1]})")
    print(f"  {repeats} later re-introductions, {sum(1 for r in rows if r['audio'])} with audio")
    print("  by script: " + ", ".join(f"{k}={v}" for k, v in sorted(scripts.items(), key=lambda kv: -kv[1])))
    print(f"wrote {out.relative_to(duome.SOURCE_ROOT.parent.parent)}")


if __name__ == "__main__":
    main()
