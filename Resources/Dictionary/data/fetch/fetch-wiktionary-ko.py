#!/usr/bin/env python3
"""Fetch a Korean-English dictionary from Wiktionary (via kaikki.org) into Dictionary/Korean/.

Source: kaikki.org's machine-readable extract of English Wiktionary, Korean section
(https://kaikki.org/dictionary/Korean/), CC BY-SA 4.0 / GFDL. ~21 MB compressed,
streamed and decompressed on the fly. Chosen over kengdic (MPL/LGPL, 133k rows) because
kengdic has no part of speech and its glosses are noisy ("먹다: Go deaf" sits next to
"Eat"); Wiktionary gives clean senses, romanisation and hanja for every entry.

Every lemma entry is kept (single hangul syllables as script characters, and entries
that are only "inflection of X", are not). Homographs with different hanja stay
separate rows: 가구 家口 ("household") and 가구 家具 ("furniture").

Gap filling: ~490 NIKL/TOPIK words have no Wiktionary entry at all (강의실, 관광지,
현대인 -- mostly Sino-Korean compounds). For those words only, rows are added from
kengdic (garfieldnate/kengdic, MPL 2.0 / LGPL 2+), preferring the entry whose hanja
matches the list's. kengdic is noisy, which is why it fills gaps rather than leading.

`common` is set from the NIKL learner vocabulary + TOPIK public list
(julienshim/combined_korean_vocabulary_list, MIT; derived from the National Institute
of Korean Language's 2003 list and TOPIK's 2015 published list).

Output: Korean/wiktionary-ko.csv  (CONTRACTS §3 dictionary schema)

    headword  hangul
    reading   Revised Romanisation, as Wiktionary gives it (meokda)
    forms     hanja spellings, pipe-separated (學校)
    readings  empty
    pos       n|v|adj|adv|pron|num|det|prt|int|suf|pref|ctr|exp
    senses    English glosses, pipe-separated (at most 12)
    common    1 if the word is in the NIKL learner list or the TOPIK list

Usage:
    python fetch-wiktionary-ko.py
    python fetch-wiktionary-ko.py --full     # same output; accepted for interface symmetry
"""

from __future__ import annotations

import argparse
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import _fetchlib as lib  # noqa: E402
import _korean  # noqa: E402

CODE = "ko"
SOURCE = "wiktionary-ko"
KENGDIC = "https://raw.githubusercontent.com/garfieldnate/kengdic/master/kengdic.tsv"


def kengdic_rows(missing: dict[str, list[dict]]) -> list[dict]:
    """Rows for listed words Wiktionary lacks, from kengdic. `missing`: word -> list rows."""
    import csv
    import io

    text = lib.get_text(KENGDIC)
    found: dict[str, list[dict]] = {}
    for row in csv.DictReader(io.StringIO(text), delimiter="\t"):
        word = (row.get("surface") or "").strip()
        gloss = lib.clean_gloss(row.get("gloss") or "")
        if word in missing and gloss:
            found.setdefault(word, []).append({"gloss": gloss, "hanja": (row.get("hanja") or "").strip()})
    out = []
    for word, entries in found.items():
        listed = missing[word]
        wanted_hanja = {r["hanja"] for r in listed if r["hanja"]}
        best = [e for e in entries if e["hanja"] in wanted_hanja] or entries
        pos = [_korean.POS[r["part_of_speech"]] for r in listed if r["part_of_speech"] in _korean.POS]
        out.append({
            "headword": word,
            "reading": "",
            "forms": "|".join(dict.fromkeys(e["hanja"] for e in best if e["hanja"])),
            "readings": "",
            "pos": "|".join(dict.fromkeys(pos)),
            "senses": "|".join(dict.fromkeys(e["gloss"] for e in best[:4])),
            "common": "1",
        })
    return out


def output() -> Path:
    return lib.dictionary_dir(CODE) / f"{SOURCE}.csv"


def fetch(full: bool = False) -> None:
    timer = lib.Timer()
    listed: dict[str, set[str]] = {}
    list_rows: dict[str, list[dict]] = {}
    for row in _korean.load():
        listed.setdefault(row["word"], set()).add(row["hanja"])
        list_rows.setdefault(row["word"], []).append(row)

    groups: dict[tuple[str, str], dict] = {}
    seen = 0
    for entry in lib.kaikki_stream(lib.language(CODE)["name"]):
        seen += 1
        pos = entry.get("pos")
        if pos in lib.KAIKKI_SKIP:
            continue
        word = unicodedata.normalize("NFC", entry.get("word", "")).strip()
        if not word or " " in word:
            continue
        templates = {h.get("name", "") for h in entry.get("head_templates", [])}
        if any(name.endswith("-form") for name in templates):
            continue  # conjugated forms (감사합니다 as "formal indicative of 감사하다")
        real, _ = lib.sense_glosses(entry)
        if not real:
            continue
        hanja = [f for f in lib.entry_forms(entry, "hanja", min_len=1) if f != word]
        roman = [f["form"].rstrip("?!.") for f in entry.get("forms", []) if "romanization" in f.get("tags", [])]
        g = groups.setdefault((word, hanja[0] if hanja else ""),
                              {"roman": [], "hanja": [], "pos": [], "senses": []})
        g["roman"] += [r for r in roman if r not in g["roman"]]
        g["hanja"] += [h for h in hanja if h not in g["hanja"]]
        tag = lib.KAIKKI_POS.get(pos, pos)
        if tag not in g["pos"]:
            g["pos"].append(tag)
        g["senses"] += [s for s in real if s not in g["senses"]]

    rows = []
    for (word, first_hanja), g in groups.items():
        known = listed.get(word)
        common = known is not None and ("" in known or not g["hanja"] or bool(known & set(g["hanja"])))
        rows.append({
            "headword": word,
            "reading": g["roman"][0] if g["roman"] else "",
            "forms": "|".join(g["hanja"]),
            "readings": "",
            "pos": "|".join(g["pos"]),
            "senses": "|".join(g["senses"][: lib.MAX_SENSES]),
            "common": "1" if common else "0",
        })
    have = {word for word, _ in groups}
    filled = kengdic_rows({w: rs for w, rs in list_rows.items() if w not in have})
    rows += filled
    rows.sort(key=lambda r: (r["common"] != "1", r["headword"]))
    if len(rows) < 10_000:
        raise lib.FetchError(f"only {len(rows)} entries parsed -- kaikki format changed?")
    path = output()
    n = lib.write_csv(path, lib.DICTIONARY_COLUMNS, rows)
    common = sum(r["common"] == "1" for r in rows)
    print(f"  {seen:,} Wiktionary entries read; {len(filled):,} listed words filled from kengdic")
    print(f"wrote {lib.rel(path)}: {n:,} rows ({common:,} common/NIKL-TOPIK), "
          f"{path.stat().st_size / 1024 / 1024:.1f} MB in {timer}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--full", action="store_true", help="no effect: every lemma is already kept")
    args = ap.parse_args()
    fetch(args.full)


if __name__ == "__main__":
    lib.run(main)
