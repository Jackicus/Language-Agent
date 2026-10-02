"""Shared plumbing for the Resources fetchers. Stdlib only.

Not a fetcher itself. Every `fetch-*.py` under Resources/*/data/fetch/ that needs more
than a single download imports this, so the network-failure behaviour (CONTRACTS §4:
one line, non-zero exit, no traceback), the CSV dialect and the file naming are the same
everywhere.

Also holds the two pieces of logic shared across languages:

- the kaikki.org (Wiktionary) streaming reader used by every `fetch-wiktionary-*.py`
- the frequency-band builder used by every `fetch-freq-*.py`
"""

from __future__ import annotations

import csv
import gzip
import http.client
import io
import json
import re
import socket
import sys
import time
import unicodedata
import urllib.error
import urllib.request
import zlib
from pathlib import Path
from typing import Callable, Iterable, Iterator

ROOT = Path(__file__).resolve().parent.parent  # project root
RESOURCES = ROOT / "Resources"
REGISTRY = ROOT / "languages.json"
USER_AGENT = "Language-Agent/1.0 (+https://github.com/; resource fetcher)"

DICTIONARY_COLUMNS = ["headword", "reading", "forms", "readings", "pos", "senses", "common"]
TEST_COLUMNS = ["level", "expression", "reading", "meaning", "tags"]

# Everything that can go wrong on the wire, including a stream cut mid-way through a
# gzip body (EOFError / zlib.error) and a server that hangs up early (IncompleteRead).
NETWORK_ERRORS = (
    urllib.error.URLError,
    http.client.HTTPException,
    socket.timeout,
    TimeoutError,
    ConnectionError,
    EOFError,
    zlib.error,
    gzip.BadGzipFile,
)


class FetchError(Exception):
    """A failure worth one line to the user (bad payload, missing asset)."""


# ── registry ────────────────────────────────────────────────────────────────────────


def language(code: str) -> dict:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    return registry[code]


def tests_dir(code: str) -> Path:
    return RESOURCES / "Tests" / language(code)["name"]


def dictionary_dir(code: str) -> Path:
    return RESOURCES / "Dictionary" / language(code)["name"]


def level_filename(source: str, level: str) -> str:
    """`hsk`+`HSK1` -> `hsk-1.csv`; `jlpt`+`N5` -> `jlpt-n5.csv`; `freq-fr`+`A1` -> `freq-fr-a1.csv`.

    The level label loses its own copy of the source prefix, so CONTRACTS §3's example
    (`hsk-1.csv`) holds. Consumers should read the `level` column, not parse this.
    """
    label = level.lower()
    head = source.lower().split("-")[0]
    if label.startswith(head) and label != head:
        label = label[len(head):]
    return f"{source}-{label}.csv"


# ── network ─────────────────────────────────────────────────────────────────────────


def get(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def get_text(url: str, timeout: int = 120) -> str:
    return get(url, timeout).decode("utf-8", errors="replace")


def head_size(url: str) -> int | None:
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            size = resp.headers.get("Content-Length")
            return int(size) if size else None
    except NETWORK_ERRORS:
        return None


def stream_gzip_lines(url: str, timeout: int = 120) -> Iterator[str]:
    """Yield decoded lines of a remote .gz file without holding it in memory or on disk."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        with gzip.GzipFile(fileobj=resp) as gz:
            yield from io.TextIOWrapper(gz, encoding="utf-8", errors="replace")


def run(main: Callable[[], None]) -> None:
    """Run a fetcher's main(), turning network and payload failures into one line."""
    try:
        main()
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        sys.exit(130)
    except urllib.error.HTTPError as exc:
        print(f"error: HTTP {exc.code} fetching {exc.url}", file=sys.stderr)
        sys.exit(1)
    except NETWORK_ERRORS as exc:
        reason = getattr(exc, "reason", None) or exc
        print(f"error: network failure: {reason}", file=sys.stderr)
        sys.exit(1)
    except FetchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)


def mb(n: int | None) -> str:
    return "unknown size" if n is None else f"{n / 1024 / 1024:.0f} MB"


# ── output ──────────────────────────────────────────────────────────────────────────


def write_csv(path: Path, columns: list[str], rows: Iterable[dict]) -> int:
    """Write UTF-8 with BOM (as the Japanese files always have been). Returns row count."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    count = 0
    with tmp.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
            count += 1
    tmp.replace(path)  # a failed run never leaves a half-written table behind
    return count


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def clean_gloss(text: str) -> str:
    """Senses are `|`-separated in the dictionary schema, so a gloss may not contain one."""
    return " ".join(text.replace("|", "/").split())


class Timer:
    def __init__(self) -> None:
        self.start = time.monotonic()

    def __str__(self) -> str:
        return f"{time.monotonic() - self.start:.1f}s"


# ── part-of-speech tags ─────────────────────────────────────────────────────────────

# Wiktionary (kaikki) POS -> the JMdict-style short tags of CONTRACTS §3. Tags with no
# JMdict equivalent keep a short self-explanatory name (prep, det, contr).
KAIKKI_POS = {
    "noun": "n", "verb": "v", "adj": "adj", "adv": "adv", "pron": "pron", "num": "num",
    "conj": "conj", "particle": "prt", "postp": "prt", "intj": "int", "suffix": "suf",
    "prefix": "pref", "phrase": "exp", "prep_phrase": "exp", "proverb": "exp",
    "prep": "prep", "det": "det", "article": "det", "contraction": "contr",
    "counter": "ctr", "name": "n",
}

# Never vocabulary: single letters, scripts, symbols, romanisation stubs.
KAIKKI_SKIP = {
    "character", "symbol", "punct", "romanization", "syllable", "letter", "infix",
    "interfix", "affix", "root", "abbrev",
}


# ── kaikki.org (Wiktionary) ─────────────────────────────────────────────────────────

KAIKKI_URL = "https://kaikki.org/dictionary/{name}/kaikki.org-dictionary-{name}.jsonl.gz"

# Form-table noise kaikki carries alongside real inflected forms.
_FORM_NOISE_TAGS = {
    "table-tags", "inflection-template", "class", "romanization", "multiword-construction",
    # not spellings of this word: the auxiliary (haben, avere), the dictionary's stress-
    # marked display form (mangiàre), and derived words (Kätzchen, gattino)
    "auxiliary", "canonical", "diminutive", "augmentative", "pejorative", "endearing",
    # forms no learner will meet
    "obsolete", "archaic", "dated", "misspelling",
}


def kaikki_stream(name: str) -> Iterator[dict]:
    url = KAIKKI_URL.format(name=name)
    size = head_size(url)
    print(f"streaming {url.rsplit('/', 1)[-1]} ({mb(size)} compressed) ...", flush=True)
    for line in stream_gzip_lines(url, timeout=300):
        if line.strip():
            yield json.loads(line)


def _is_plain_word(form: str) -> bool:
    """A real spelling: letters, apostrophes, hyphens -- no IPA, digits or spaces."""
    if not form or " " in form or form.startswith("-") and len(form) == 1:
        return False
    for ch in unicodedata.normalize("NFC", form):
        if ch in "'’-":
            continue
        cat = unicodedata.category(ch)
        if not cat.startswith("L"):
            return False
        if 0x0250 <= ord(ch) <= 0x02AF:  # IPA extensions leak into some form tables
            return False
    return True


# "a: the name of the Latin-script letter A" -- a letter, not vocabulary, and a lemma
# for it would swallow the frequency of French "a" (has).
LETTER_NAME = re.compile(r"\bname of the [\w -]*letter\b", re.I)


def sense_glosses(entry: dict) -> tuple[list[str], list[str]]:
    """(real glosses, form-of/alt-of targets) for one kaikki entry."""
    real, targets = [], []
    for sense in entry.get("senses", []):
        tags = set(sense.get("tags", []))
        links = (sense.get("form_of") or []) + (sense.get("alt_of") or [])
        if links or "form-of" in tags or "alt-of" in tags:
            targets += [link["word"] for link in links if link.get("word")]
            continue
        glosses = sense.get("glosses") or []
        if glosses and not LETTER_NAME.search(glosses[-1]):
            # Sub-senses repeat their parent's gloss first; the last one is the sense.
            real.append(clean_gloss(glosses[-1]))
    return list(dict.fromkeys(g for g in real if g)), targets


def unstress(form: str) -> str:
    """Italian: Wiktionary marks stress on every vowel (màngio); standard spelling only
    writes an accent on a final vowel (perché, città). Drop the non-final ones."""
    decomposed = unicodedata.normalize("NFD", form)
    last = max((i for i, ch in enumerate(decomposed) if not unicodedata.combining(ch)), default=-1)
    kept = "".join(ch for i, ch in enumerate(decomposed)
                   if not (ch in "\u0300\u0301" and i < last))
    return unicodedata.normalize("NFC", kept)


def entry_forms(entry: dict, tag: str | None = None, stress_marked: bool = False,
                min_len: int = 2) -> list[str]:
    out = []
    for f in entry.get("forms", []):
        tags = set(f.get("tags", []))
        if tags & _FORM_NOISE_TAGS:
            continue
        if tag is not None and tag not in tags:
            continue
        form = f.get("form", "")
        if stress_marked:
            form = unstress(form)
        if len(form) >= min_len and _is_plain_word(form):
            out.append(unicodedata.normalize("NFC", form))
    return list(dict.fromkeys(out))


# ── frequency lists ─────────────────────────────────────────────────────────────────

FREQ_URL = "https://raw.githubusercontent.com/hermitdave/FrequencyWords/master/content/2018/{code}/{code}_50k.txt"


def frequency_list(code: str) -> list[str]:
    """OpenSubtitles 2018 word list, most frequent first, casefolded, deduplicated."""
    text = get_text(FREQ_URL.format(code=code))
    words = []
    for line in text.splitlines():
        parts = line.split()
        if parts:
            words.append(unicodedata.normalize("NFC", parts[0]).casefold())
    words = list(dict.fromkeys(words))
    if len(words) < 10_000:
        raise FetchError(f"frequency list for {code} has only {len(words)} words -- source changed?")
    return words


def elision_tokens(phrase: str) -> list[str]:
    """Split a phrase the way the frequency list tokenises: spaces, and after an apostrophe."""
    out = []
    for token in phrase.casefold().split():
        out += [t for t in re.split(r"(?<=['’])", token) if t]
    return out


# ── Latin-script languages: Wiktionary dictionary + frequency bands ─────────────────

# How far down the frequency list the dictionary reaches. A lemma is kept when its own
# spelling or any of its inflected forms is among these words.
FREQ_SCOPE = 50_000
# A lemma is `common` when it (or a form of it) is among this many most frequent words.
COMMON_RANK = 10_000
MAX_SENSES = 12
PHRASE_POS = {"phrase", "intj", "prep_phrase", "adv", "prep", "conj"}


def latin_dictionary(name: str, freq_code: str, full: bool) -> tuple[list[dict], dict]:
    """Build dictionary rows (lemma per row, inflections in `forms`) from kaikki.

    Returns (rows, stats). Rows are ordered most frequent first.
    """
    words = frequency_list(freq_code)
    rank = {w: i for i, w in enumerate(words)}
    scope = set(words[:FREQ_SCOPE])

    lemmas: dict[str, dict] = {}
    links: list[tuple[str, list[str]]] = []
    seen = 0
    for entry in kaikki_stream(name):
        seen += 1
        pos = entry.get("pos")
        if pos in KAIKKI_SKIP or pos == "name":
            continue
        word = unicodedata.normalize("NFC", entry.get("word", "")).strip()
        if not word or any(ch.isdigit() for ch in word):
            continue
        real, targets = sense_glosses(entry)
        if not real:
            # Inflected or alternative spelling: remember it so the lemma lists it.
            if targets and " " not in word:
                links.append((word, targets))
            continue
        if " " in word and (pos not in PHRASE_POS or len(elision_tokens(word)) > 4):
            continue
        if " " not in word and not _is_plain_word(word):
            continue
        rec = lemmas.setdefault(word, {"pos": [], "senses": [], "forms": []})
        tag = KAIKKI_POS.get(pos, pos)
        if tag not in rec["pos"]:
            rec["pos"].append(tag)
        rec["senses"] += [g for g in real if g not in rec["senses"]]
        forms = entry_forms(entry, stress_marked=(name == "Italian"))
        rec["forms"] += [f for f in forms if f != word and f not in rec["forms"]]

    for form, targets in links:
        # A word that is a lemma in its own right is not folded into another one: "de"
        # carries an alt-of sense pointing at "dame", and folding it would rank "dame"
        # as the most frequent word in French.
        if form in lemmas or len(form) < 2:
            continue
        for target in targets:
            rec = lemmas.get(target)
            if rec is not None and form != target and form not in rec["forms"]:
                rec["forms"].append(form)

    rows = []
    for word, rec in lemmas.items():
        if " " in word:
            tokens = elision_tokens(word)
            if not all(t in scope for t in tokens):
                continue
            best = max(rank[t] for t in tokens)
        else:
            candidates = [rank[w] for w in [word.casefold()] + [f.casefold() for f in rec["forms"]] if w in rank]
            best = min(candidates) if candidates else None
            if not full and (best is None or best >= FREQ_SCOPE):
                continue
        rows.append((best if best is not None else len(words), word, rec))

    rows.sort(key=lambda r: (r[0], r[1]))
    out = [
        {
            "headword": word,
            "reading": "",
            "forms": "|".join(rec["forms"]),
            "readings": "",
            "pos": "|".join(rec["pos"]),
            "senses": "|".join(rec["senses"][:MAX_SENSES]),
            "common": "1" if best < COMMON_RANK else "0",
        }
        for best, word, rec in rows
    ]
    stats = {"entries": seen, "lemmas": len(lemmas), "frequency_words": len(words)}
    return out, stats


# Cumulative band edges for the six CEFR labels, in lemmas. See Resources/README.md.
CEFR_BANDS = [500, 1_500, 3_500, 6_500, 11_500]


def frequency_bands(code: str, source: str, freq_code: str, dictionary: Path,
                    run_dictionary: Callable[[], None], wanted: list[str] | None) -> None:
    """Write <source>-<level>.csv for a Latin-script language from frequency + dictionary."""
    meta = language(code)
    levels = meta["tests"]["levels"]
    if len(levels) != len(CEFR_BANDS) + 1:
        raise FetchError(f"{code}: expected {len(CEFR_BANDS) + 1} levels, registry has {levels}")
    wanted = [w.upper() for w in wanted] if wanted else levels
    bad = [w for w in wanted if w not in levels]
    if bad:
        raise FetchError(f"unknown level(s) {bad} -- expected any of {levels}")

    if not dictionary.exists():
        print(f"{rel(dictionary)} missing -- fetching the dictionary first")
        run_dictionary()
    rows = read_csv(dictionary)

    words = frequency_list(freq_code)[:FREQ_SCOPE]
    own_rank = {w: i for i, w in enumerate(words)}
    by_head: dict[str, list[dict]] = {}
    by_form: dict[str, list[dict]] = {}
    for row in rows:
        head = row["headword"]
        if " " in head:
            continue  # phrases have no frequency of their own
        if len(head) > 1 and head.isupper():
            continue  # acronyms (VA, CE) are not graded vocabulary
        by_head.setdefault(row["headword"].casefold(), []).append(row)
        for form in filter(None, row["forms"].split("|")):
            by_form.setdefault(form.casefold(), []).append(row)

    emitted: dict[str, tuple[int, dict]] = {}
    unmatched = 0
    for i, word in enumerate(words):
        # A frequency word that spells a lemma credits that lemma only; one that does not
        # credits the lemma it inflects. Crediting both was tried: it promotes every
        # lemma that happens to have a frequent form as a homograph -- mai (via "mais"),
        # dan (via "dans"), nadar (via "nada") -- far more noise than it fixes.
        # When several lemmas claim a form, only the one whose own spelling is most
        # frequent counts: "suis" -> être (not suivre), "les" -> le (not ils, elles,
        # iels, which list it as a paradigm form).
        candidates = by_head.get(word, [])
        if code != "de" and len(candidates) > 1:
            # The frequency list is casefolded, so "são" cannot tell São (saint) from são
            # (are). Outside German, a capitalised headword is a name-like use: prefer
            # the lowercase lemma when there is one. German capitalises every noun, so
            # Essen and essen both stand.
            candidates = [r for r in candidates if r["headword"] == r["headword"].lower()] or candidates
        if not candidates:
            candidates = by_form.get(word, [])
            if len(candidates) > 1:
                ranks = [own_rank.get(r["headword"].casefold(), len(words)) for r in candidates]
                best = min(ranks)
                candidates = [r for r, k in zip(candidates, ranks) if k == best]
        if not candidates:
            unmatched += 1
            continue
        for row in candidates:
            if row["headword"] not in emitted:
                emitted[row["headword"]] = (i, row)

    ordered = sorted(emitted.values(), key=lambda t: t[0])
    edges = CEFR_BANDS + [len(ordered)]
    out_dir = tests_dir(code)
    total = 0
    start = 0
    for level, edge in zip(levels, edges):
        band = ordered[start:edge]
        start = edge
        if level not in wanted:
            continue
        table = [
            {
                "level": level,
                "expression": row["headword"],
                "reading": "",
                "meaning": "; ".join(row["senses"].split("|")[:6]),
                "tags": "frequency-band",
            }
            for _, row in band
        ]
        path = out_dir / level_filename(source, level)
        n = write_csv(path, TEST_COLUMNS, table)
        total += n
        first = band[0][0] + 1 if band else 0
        last = band[-1][0] + 1 if band else 0
        print(f"  {level}: {n:,} lemmas (frequency ranks {first:,}-{last:,}) -> {rel(path)}")
    print(f"{total:,} lemmas across {len(wanted)} level(s); "
          f"{unmatched:,} of the top {len(words):,} frequency words had no dictionary gloss and were dropped")
