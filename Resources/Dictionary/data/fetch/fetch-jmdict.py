#!/usr/bin/env python3
"""Fetch a Japanese dictionary table from JMdict into Connections/Dictionary/Japanese/.

Why this connection exists: Duolingo gives a surface form and an English gloss, and for
kanji-only entries (東京, 京都, 私) it gives no reading at all. That leaves the lexicon
unable to answer two basic questions -- how is this pronounced, and is this the same word
as the kanji/kana spelling some other source used.

JMdict answers both. Every entry groups the kanji spellings and the kana readings of one
word, so it doubles as a variant table: look up たべもの and you get 食べ物, which is what
the JLPT lists actually contain.

Uses the "common" subset of jmdict-simplified (~1.4 MB compressed, ~30k entries) rather
than the full 200k-entry file. The full file is mostly rare and archaic vocabulary that
no beginner course will ever surface, and it would triple the lexicon build time.

Output: Japanese/jmdict.csv

    kanji     primary kanji spelling ("" if the word is kana-only)
    kana      primary kana reading
    kanji_all all kanji spellings, pipe-separated
    kana_all  all kana readings, pipe-separated
    pos       parts of speech, pipe-separated
    senses    English glosses, pipe-separated
    common    1 if JMdict marks the word common

Usage:
    python fetch-jmdict.py
    python fetch-jmdict.py --full     # all ~200k entries instead of the common subset
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import urllib.request
import zipfile
from pathlib import Path

RELEASES = "https://api.github.com/repos/scriptin/jmdict-simplified/releases/latest"
HERE = Path(__file__).resolve().parent
CONNECTION_ROOT = HERE.parent.parent
OUT_DIR = CONNECTION_ROOT / "Japanese"
COLUMNS = ["kanji", "kana", "kanji_all", "kana_all", "pos", "senses", "common"]


def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Language-Agent/1.0"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        return resp.read()


def find_asset(full: bool) -> tuple[str, str]:
    """Locate the right asset on the latest release.

    The filename carries the version and build timestamp, so it changes on every
    release -- it has to be discovered rather than hardcoded.
    """
    release = json.loads(get(RELEASES))
    want = "jmdict-eng-" if full else "jmdict-eng-common-"
    for asset in release.get("assets", []):
        name = asset["name"]
        if name.startswith(want) and name.endswith(".json.zip"):
            # The common file also starts with "jmdict-eng-", so reject it when asked
            # for the full set.
            if full and "common" in name:
                continue
            return name, asset["browser_download_url"]
    raise SystemExit(f"No {want}*.json.zip asset on release {release.get('tag_name')}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--full", action="store_true", help="use the complete JMdict instead of common words")
    args = ap.parse_args()

    name, url = find_asset(args.full)
    print(f"downloading {name} ...")
    blob = get(url)

    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        inner = zf.namelist()[0]
        data = json.loads(zf.read(inner).decode("utf-8"))

    rows = []
    for word in data["words"]:
        kanji = [k["text"] for k in word.get("kanji", [])]
        kana = [k["text"] for k in word.get("kana", [])]
        if not kana:
            continue
        senses, pos = [], []
        for sense in word.get("sense", []):
            pos += sense.get("partOfSpeech", [])
            senses += [g["text"] for g in sense.get("gloss", []) if g.get("lang") == "eng"]
        common = any(k.get("common") for k in word.get("kanji", [])) or any(k.get("common") for k in word.get("kana", []))
        rows.append({
            "kanji": kanji[0] if kanji else "",
            "kana": kana[0],
            "kanji_all": "|".join(dict.fromkeys(kanji)),
            "kana_all": "|".join(dict.fromkeys(kana)),
            "pos": "|".join(dict.fromkeys(pos)),
            "senses": "|".join(dict.fromkeys(senses)),
            "common": "1" if common else "0",
        })

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "jmdict.csv"
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    with_kanji = sum(1 for r in rows if r["kanji"])
    print(f"  {len(rows):,} entries ({with_kanji:,} with a kanji spelling)")
    print(f"  version {data.get('version')} · dict date {data.get('dictDate')}")
    print(f"wrote {out.relative_to(CONNECTION_ROOT.parent.parent)} ({out.stat().st_size / 1024 / 1024:.1f} MB)")


if __name__ == "__main__":
    main()
