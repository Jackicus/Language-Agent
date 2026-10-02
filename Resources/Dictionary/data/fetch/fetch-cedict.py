#!/usr/bin/env python3
"""Fetch CC-CEDICT, the open Chinese-English dictionary, into Dictionary/Chinese/.

Source: MDBG's CC-CEDICT export (https://www.mdbg.net/chinese/dictionary?page=cedict),
CC BY-SA 4.0. A single gzipped text file, ~4 MB, republished daily under a fixed name.
HSK membership for `common` and parts of speech come from
drkameleon/complete-hsk-vocabulary (MIT), since CEDICT itself carries neither.

One row per (simplified, pinyin) pair -- CEDICT's own unit is a line per traditional
spelling and reading, so 行 xíng ("to walk") and 行 háng ("row") stay separate words,
while 水 shuǐ and the surname 水 Shuǐ merge into one.

By default, entries that are nothing but "variant of X" / "old variant of X" are left
out (they are pointers, not words); --full keeps them.

Output: Chinese/cedict.csv  (CONTRACTS §3 dictionary schema)

    headword  simplified hanzi
    reading   pinyin with tone marks, syllables space-separated (xiè xie), matching
              the HSK lists' `reading`
    forms     traditional spellings, pipe-separated (includes the simplified one when
              they are the same character)
    readings  the same pinyin in CEDICT's tone-number form (xie4 xie5), pipe-separated
    pos       from the HSK data where the word is listed (n|v|adj|adv|...); else empty
    senses    English glosses, pipe-separated; classifier notes (CL:...) dropped
    common    1 if the word, with this reading, is in any HSK 2.0 or 3.0 list

Usage:
    python fetch-cedict.py
    python fetch-cedict.py --full
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import _fetchlib as lib  # noqa: E402

CODE = "zh"
SOURCE = "cedict"
URL = "https://www.mdbg.net/chinese/export/cedict/cedict_1_0_ts_utf-8_mdbg.txt.gz"
HSK_URL = "https://raw.githubusercontent.com/drkameleon/complete-hsk-vocabulary/main/complete.min.json"
LINE = re.compile(r"^(\S+) (\S+) \[([^\]]*)\] /(.*)/\s*$")
VARIANT = re.compile(r"^(old |archaic |ancient |obscure |Japanese |erroneous )?variant of ", re.I)

# HSK part-of-speech tags (ICTCLAS-style) -> CONTRACTS §3 short tags.
HSK_POS = {
    "n": "n", "nr": "n", "ns": "n", "nt": "n", "nz": "n", "t": "n", "f": "n", "s": "n",
    "v": "v", "vn": "v", "vd": "v", "a": "adj", "ad": "adj", "an": "adj", "b": "adj",
    "d": "adv", "r": "pron", "m": "num", "q": "ctr", "p": "prep", "c": "conj",
    "u": "prt", "y": "prt", "e": "int", "o": "int", "i": "exp", "l": "exp",
    "k": "suf", "h": "pref",
}

TONE_MARKS = {
    "a": "āáǎà", "e": "ēéěè", "i": "īíǐì", "o": "ōóǒò", "u": "ūúǔù", "ü": "ǖǘǚǜ",
}


def mark_syllable(syl: str) -> str:
    """xie4 -> xiè, lu:3 -> lǚ, r5 -> r. Syllables without a tone digit pass through."""
    m = re.fullmatch(r"([A-Za-zÜü:]+)([1-5])", syl)
    if not m:
        return syl.replace("u:", "ü").replace("U:", "Ü")
    body, tone = m.group(1).replace("u:", "ü").replace("U:", "Ü").replace("v", "ü"), int(m.group(2))
    if tone == 5:
        return body
    lower = body.lower()
    if "a" in lower:
        i = lower.index("a")
    elif "e" in lower:
        i = lower.index("e")
    elif "ou" in lower:
        i = lower.index("o")
    else:
        vowels = [k for k, ch in enumerate(lower) if ch in "aeiouü"]
        if not vowels:
            return body  # m2, ng4 -- no vowel to carry the mark
        i = vowels[-1]
    ch = lower[i]
    marked = TONE_MARKS[ch][tone - 1]
    if body[i].isupper():
        marked = marked.upper()
    return body[:i] + marked + body[i + 1:]


def to_marks(pinyin: str) -> str:
    return " ".join(mark_syllable(s) for s in pinyin.split())


def pinyin_key(pinyin: str) -> str:
    """Comparable numbered pinyin: lowercase, single spaces, ü however it was spelled."""
    return " ".join(pinyin.lower().replace("u:", "ü").replace("v", "ü").split())


def load_hsk() -> dict[tuple[str, str], list[str]]:
    """(simplified, lowercase numbered pinyin) -> HSK part-of-speech tags."""
    data = json.loads(lib.get(HSK_URL))
    out = {}
    for word in data:
        pos = [HSK_POS[p] for p in word.get("p", []) if p in HSK_POS]
        for form in word.get("f", []):
            key = (word["s"], pinyin_key(form.get("i", {}).get("n", "")))
            out[key] = list(dict.fromkeys(pos))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--full", action="store_true", help="also keep variant-only entries")
    args = ap.parse_args()
    timer = lib.Timer()

    print(f"downloading {URL.rsplit('/', 1)[-1]} ...")
    text = gzip.decompress(lib.get(URL)).decode("utf-8")
    hsk = load_hsk()

    groups: dict[tuple[str, str], dict] = {}
    lines = skipped = 0
    for line in text.splitlines():
        if line.startswith("#"):
            continue
        m = LINE.match(line)
        if not m:
            continue
        lines += 1
        trad, simp, pinyin, body = m.groups()
        pinyin = " ".join(pinyin.split())
        senses = [lib.clean_gloss(s) for s in body.split("/") if s and not s.startswith("CL:")]
        if not args.full and senses and all(VARIANT.match(s) for s in senses):
            skipped += 1
            continue
        key = (simp, pinyin_key(pinyin))
        g = groups.setdefault(key, {"pinyin": [], "trad": [], "senses": []})
        g["pinyin"].append(pinyin)
        g["trad"].append(trad)
        # Proper-noun lines (capitalised pinyin: surnames, places) sort after the rest.
        g["senses"] += [(pinyin[:1].isupper(), s) for s in senses]

    rows = []
    for (simp, low), g in groups.items():
        # Prefer the common-noun spelling of the reading (shui3 over Shui3).
        pinyin = sorted(dict.fromkeys(g["pinyin"]), key=lambda p: (p[:1].isupper(), p))
        pos = hsk.get((simp, low))
        rows.append({
            "headword": simp,
            "reading": to_marks(pinyin[0]),
            "forms": "|".join(dict.fromkeys(g["trad"])),
            "readings": "|".join(pinyin),
            "pos": "|".join(pos or []),
            "senses": "|".join(dict.fromkeys(s for _, s in sorted(g["senses"], key=lambda x: x[0]))),
            "common": "1" if pos is not None else "0",
        })

    if len(rows) < 50_000:
        raise lib.FetchError(f"only {len(rows)} entries parsed -- CEDICT format changed?")
    path = lib.dictionary_dir(CODE) / f"{SOURCE}.csv"
    n = lib.write_csv(path, lib.DICTIONARY_COLUMNS, rows)
    common = sum(r["common"] == "1" for r in rows)
    print(f"  {lines:,} CEDICT lines, {skipped:,} variant-only skipped")
    print(f"wrote {lib.rel(path)}: {n:,} rows ({common:,} common/HSK), "
          f"{path.stat().st_size / 1024 / 1024:.1f} MB in {timer}")


if __name__ == "__main__":
    lib.run(main)
