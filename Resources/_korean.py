"""The NIKL/TOPIK combined list, shared by fetch-wiktionary-ko.py and fetch-topik.py."""

from __future__ import annotations

import csv
import io
import re

import _fetchlib as lib

URL = "https://raw.githubusercontent.com/julienshim/combined_korean_vocabulary_list/master/results.tsv"
HOMOGRAPH = re.compile(r"\d+$")

# NIKL part of speech -> CONTRACTS §3 tags (for picking the right dictionary homograph).
POS = {
    "명사": "n", "의존명사": "n", "고유 명사": "n", "대명사": "pron", "수사": "num",
    "동사": "v", "형용사": "adj", "보조 용언": "v", "부사": "adv", "관형사": "det",
    "감탄사": "int", "조사": "prt", "접사": "suf", "줄어든 말": "exp",
}


def load() -> list[dict]:
    """Rows with `word` stripped of its homograph number (가구03 -> 가구)."""
    text = lib.get_text(URL)
    rows = list(csv.DictReader(io.StringIO(text), delimiter="\t"))
    if len(rows) < 5_000 or "topik_level" not in rows[0]:
        raise lib.FetchError("results.tsv is not the expected NIKL/TOPIK table -- source changed?")
    for row in rows:
        row["word"] = HOMOGRAPH.sub("", row["word"].strip())
        row["hanja"] = row.get("hanja", "").strip()
    return rows
