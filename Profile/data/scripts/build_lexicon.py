#!/usr/bin/env python3
"""Build Profile/<code>/lexicon.jsonl from the connections and resources.

    Connections/  what YOU did          -> course words / cards, per connection
    Resources/    reference material    -> test lists, dictionary
    Profile/      what the lexicon is   -> the merged word store, plus your evidence

The active language is Profile/profile.json["language"], a key of languages.json
(missing -> "ja", written back). Everything language-specific -- scripts, splitting,
inflection, weights -- comes from the plugin the registry names, in languages/.

The lexicon is the union of every connection's words and the test words, deduplicated on
the dictionary entry they resolve to (so おちゃ and お茶 are one record, not two). The
dictionary fills in whatever the others leave blank -- readings above all, since
Duolingo gives none at all for kanji-only entries.

Two grading fields, deliberately separate:

    listed  bool -- is this exact word actually in a test list?
    rating  1..n -- how hard is it: len(levels) - index, so the easiest level is highest
                    (Japanese: 5 = N5 .. 1 = N1; CEFR: 6 = A1 .. 1 = C2)

コーヒー is `listed: true, rating: 5` because it is listed. アイスコーヒー is
`listed: false, rating: 5` -- not listed, but it contains コーヒー and cannot be harder
than its parts. Keeping the two apart means exam coverage stays honest while every word
still gets a usable difficulty.

Proper nouns go to Profile/<code>/names.jsonl instead. たなか and トロント are not
vocabulary, and leaving them in would let /chat "use words you know" mean reciting place
names. Detection is gloss-based (every gloss token capitalised), so it works for any
language with English glosses.

Connections: every Connections/*/data/languages/*/<languagename>.csv is merged; the
connection folder name, lowercased, is the `sources` tag. Course position comes from
that connection's profile.json. A row with seen=1 promotes unseen -> exposed regardless
of unit, and nothing more.

Usage:
    python build_lexicon.py
    python build_lexicon.py --language fr          # switch: writes profile.json first
    python build_lexicon.py --through-unit 20
    python build_lexicon.py --dry-run
    python build_lexicon.py --root DIR             # read DIR/Connections, DIR/Resources

Environment:
    LEXICON_DIR    replaces Profile/ (lexicon goes to $LEXICON_DIR/<code>/)
    LEXICON_ROOT   same as --root
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import unicodedata
from collections import Counter
from datetime import date
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
import languages  # noqa: E402

PROFILE_DIR = Path(os.environ.get("LEXICON_DIR") or Path(__file__).resolve().parents[2])
ROOT = Path(__file__).resolve().parents[3]
_DATA_ROOT = Path(os.environ.get("LEXICON_ROOT") or ROOT)
CONNECTIONS = _DATA_ROOT / "Connections"
RESOURCES = _DATA_ROOT / "Resources"
PROFILE = PROFILE_DIR / "profile.json"

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

# Everything a connection or resource owns, refreshed on every build.
DERIVED = ("kana", "kanji", "reading", "headword", "romaji", "gloss", "hints", "pos", "script",
           "variants", "listed", "rating", "rating_source", "matched", "sources", "unit",
           "unit_name", "unit_topic", "repeat_units", "audio", "seen", "language")
# Learner evidence. Never overwritten.
LEARNER = ("confidence", "seen_count", "srs", "first_seen", "last_seen")

# The order fields appear in the JSONL, so a record reads sensibly. Japanese records carry
# kana/kanji, every other language reading/headword (see the plugin's fields()).
FIELD_ORDER = ["word", "kana", "kanji", "reading", "headword", "romaji", "gloss", "hints", "pos",
               "script", "variants", "listed", "rating", "rating_source", "matched",
               "sources", "unit", "unit_name", "unit_topic", "repeat_units", "audio", "seen",
               "language", "confidence", "seen_count", "first_seen", "last_seen", "srs"]

DICTIONARY_COLUMNS = ("headword", "reading", "forms", "readings", "pos", "senses", "common")
CONNECTION_COLUMNS = ("unit", "unit_name", "unit_topic", "position", "word", "reading", "gloss",
                      "script", "repeat_units", "audio", "seen")

# Last-resort difficulty for words no list can place: where the course introduces them.
# Unit <= 100 is the easiest level, <= 250 the next, ... ; past the last band, the hardest.
COURSE_BANDS = (100, 250, 500, 800, 1100)

STOPWORDS = {"a", "an", "the", "to", "will", "am", "is", "are", "be", "been", "going",
             "do", "does", "did", "have", "has", "had", "i", "it", "one", "s", "not"}
# Demonyms read like proper nouns but are ordinary vocabulary.
DEMONYMS = {"japanese", "english", "chinese", "korean", "american", "french", "german",
            "spanish", "italian", "brazilian", "canadian", "vietnamese", "russian",
            "portuguese", "dutch", "indian", "mexican", "thai", "australian"}

# Words that carry no meaning of their own in a gloss. A Duolingo hint made only of these
# ("for", "with", "that") must equal a sense outright -- as a word-subset it would ride
# along on any sense that happens to use it ("used FOR quoting", "contrast WITH ...").
FUNCTION_WORDS = STOPWORDS | {
    "of", "in", "on", "at", "by", "for", "with", "from", "as", "about", "into", "than",
    "that", "this", "these", "those", "and", "or", "nor", "but", "if", "when", "whenever",
    "while", "was", "were", "being", "would", "can", "could", "shall", "should", "may",
    "might", "must", "its", "you", "he", "she", "we", "they", "me", "him", "her", "us",
    "them", "my", "your", "his", "our", "their", "no", "n't", "ll", "re", "ve", "d", "m"}
ARTICLES = {"a", "an", "the"}


class _Exact:
    """Stand-in plugin for helpers called without one: exact matching only."""

    @staticmethod
    def normalise(text: str) -> str:
        return text


# --------------------------------------------------------------------------- helpers
def content_words(text: str) -> set[str]:
    return {w for w in re.split(r"[^a-z']+", text.lower()) if w and w not in STOPWORDS}


def fold(text: str) -> str:
    """Strip accents from Latin letters only: café -> cafe. Kana dakuten, hangul and
    everything else pass through untouched, so this is a no-op for CJK text."""
    out = []
    for ch in unicodedata.normalize("NFD", text):
        if unicodedata.combining(ch) and out and unicodedata.name(out[-1], "").startswith("LATIN"):
            continue
        out.append(ch)
    return unicodedata.normalize("NFC", "".join(out))


def written(entry: dict | None) -> str | None:
    """The entry's written form when it differs from its reading: 中国 for ちゅうごく.
    None for a reading-only entry (kana-only JMdict words)."""
    if not entry:
        return None
    headword = entry.get("headword") or ""
    return headword if headword and headword != (entry.get("reading") or "") else None


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


# ------------------------------------------------------------------------ loading
def language_files(name: str) -> list[tuple[str, Path]]:
    """(connection folder, table) for every connection that has words in this language."""
    found = sorted(CONNECTIONS.glob(f"*/data/languages/*/{name.lower()}.csv"))
    return [(p.relative_to(CONNECTIONS).parts[0], p) for p in found]


def read_course(wordlist: Path, code: str) -> dict:
    """The course entry in the connection's profile.json this table belongs to."""
    connection_root = wordlist.parents[3]
    path = connection_root / "profile.json"
    if not path.exists():
        return {}
    try:
        profile = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    courses = profile.get("courses") or {}
    wanted = wordlist.relative_to(connection_root).as_posix()
    for course in courses.values():
        if isinstance(course, dict) and course.get("wordlist") == wanted:
            return course
    duo = languages.spec(code).get("duolingo") or code
    for key, course in courses.items():
        if isinstance(course, dict) and (course.get("learning_language") == duo or key.endswith(f"-{duo}")):
            return course
    return {}


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _resource_files(folder: Path, source: str | None) -> list[Path]:
    if not folder.exists():
        return []
    files = sorted(folder.glob(f"{source}-*.csv" if source else "*.csv"))
    return files or ([] if source is None else sorted(folder.glob(f"{source}.csv")))


def load_tests(name: str, source: str | None = None, order: list[str] | None = None) -> list[dict]:
    """Test-list rows. Rows whose level is not one of `order` are dropped, with a warning."""
    rows = []
    for path in _resource_files(RESOURCES / "Tests" / name, source):
        rows += [r for r in read_csv(path) if r.get("expression")]
    if order is not None:
        bad = Counter(r.get("level") for r in rows if r.get("level") not in order)
        if bad:
            print(f"  warning: ignored {sum(bad.values())} test rows with unknown levels "
                  f"{sorted(bad)} (registry levels: {order})", file=sys.stderr)
        rows = [r for r in rows if r.get("level") in order]
    return rows


def load_dictionary(name: str, source: str | None = None) -> list[dict]:
    """Resources/Dictionary/<Name>/<source>.csv in the generic schema (CONTRACTS section 3).
    With no source named, every CSV in the folder is used."""
    folder = RESOURCES / "Dictionary" / name
    paths = [folder / f"{source}.csv"] if source else sorted(folder.glob("*.csv")) if folder.exists() else []
    rows = []
    for path in paths:
        if not path.exists():
            continue
        with path.open(encoding="utf-8-sig", newline="") as fh:
            header = next(csv.reader(fh), [])
        missing = [c for c in DICTIONARY_COLUMNS if c not in header]
        if missing:
            if "kanji_all" in header or "kana_all" in header:
                raise SystemExit(f"{rel(path)} uses the old JMdict columns (kanji, kana, kanji_all, kana_all). "
                                 f"Re-run  python Resources/Dictionary/data/fetch/fetch-jmdict.py  to rewrite it "
                                 f"as {', '.join(DICTIONARY_COLUMNS)}.")
            raise SystemExit(f"{rel(path)} is missing dictionary columns {missing}; "
                             f"expected {', '.join(DICTIONARY_COLUMNS)}.")
        rows += read_csv(path)
    return rows


# --------------------------------------------------------------------- dictionary
def index_dictionary(entries: list[dict], lang=None) -> dict[str, list[dict]]:
    """Surface form -> entries. A list, because 時 belongs to both とき and (rarely) 秋."""
    norm = (lang or _Exact).normalise
    index: dict[str, list[dict]] = {}
    for entry in entries:
        for form in (entry.get("forms") or "").split("|") + (entry.get("readings") or "").split("|"):
            if form:
                index.setdefault(norm(form), []).append(entry)
        # A headword not repeated in forms/readings must still find its own entry.
        for form in (entry.get("headword"), entry.get("reading")):
            if form and entry not in index.get(norm(form), []):
                index.setdefault(norm(form), []).append(entry)
    return index


def best_entry(word: str, gloss: list[str], index: dict[str, list[dict]], lang=None) -> dict | None:
    """The entry that means what the source said it means.

    Without the sense check 本 resolves to もと rather than ほん, and が to 絵.
    """
    norm = (lang or _Exact).normalise
    key = norm(word)
    candidates = index.get(key)
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    # Grammar has no English content to overlap with. は's hints are "is", "with", "for",
    # "at" ... and the one noun among them, "tooth", handed it to 歯; て went to 手 ("hand"),
    # し to 市 ("city"), いる to 射る ("to shoot"). When most hints are function words, a
    # particle, auxiliary or conjunction among the candidates is the word.
    if gloss and 2 * sum(1 for g in gloss if _function_only(g)) >= len(gloss):
        # Headword only: て must not land on って just because JMdict lists て as a variant.
        grammatical = [c for c in candidates if key in (norm(c.get("reading") or ""), norm(c.get("headword") or ""))
                       and any(p in ("prt", "conj", "cop") or p.startswith("aux") for p in (c.get("pos") or "").split("|"))]
        if grammatical:
            return grammatical[0]
    wanted = content_words(" ".join(gloss or []))

    def score(entry: dict) -> tuple[int, int]:
        return (len(content_words((entry.get("senses") or "").replace("|", " ")) & wanted),
                1 if entry.get("common") == "1" else 0)

    ranked = sorted(candidates, key=score, reverse=True)
    if score(ranked[0])[0]:
        return ranked[0]
    return next((c for c in candidates if c.get("common") == "1"), candidates[0])


# ------------------------------------------------------------------------ glosses
def _gloss_tokens(text: str, keep_parens: bool) -> list[str]:
    text = text.lower().strip()
    if not keep_parens:
        text = re.sub(r"\([^)]*\)", " ", text)
    tokens = re.findall(r"[a-z0-9]+(?:'[a-z]+)?|n't", text)
    if tokens[:1] == ["to"] and len(tokens) > 1:
        tokens = tokens[1:]
    return tokens


def _same_token(a: str, b: str) -> bool:
    """coat ~ coats, eat ~ eats ~ eating, live ~ lived. Short words must match exactly."""
    if a == b:
        return True
    short, long_ = sorted((a, b), key=len)
    if len(short) < 3 or not long_.startswith(short[:-1]):
        return False
    return long_ in {short + "s", short + "es", short + "ing", short + "d", short + "ed",
                     short[:-1] + "ing", short[:-1] + "ies"}


def _function_only(hint: str) -> bool:
    words = [t for t in _gloss_tokens(hint, keep_parens=False) if t not in ARTICLES]
    return all(t in FUNCTION_WORDS or t.endswith("n't") for t in words)


def clean_gloss(hints: list[str], entry: dict | None, trusted: bool = True) -> list[str]:
    """The course's hints that agree with the dictionary entry the word resolved to.

    Duolingo's gloss is the union of every hint shown for the token in any sentence, so
    homophones leak in: と carries "door" (戸) and "city" (都), は carries "tooth" (歯),
    さん carries "three" (三) and "Mt." (山). A hint survives if it matches one of the
    entry's senses:

      exact    same words after lowercasing, dropping "to ", trailing punctuation and
               parentheticals on both sides -- "Mr." = "Mr", "(have) not" = "not"
      subset   every word of the hint (articles aside) appears in the sense, and at
               least one is not a function word -- "green tea" in "tea (esp. green ...)"

    Plurals and -ing/-ed count as the same word (coats = coat). Duolingo's phrasing is kept
    where it agrees, since it is what the learner saw; if nothing agrees, the entry's own
    senses stand in -- but only for a `trusted` entry. When best_entry had to guess
    between homophones, nothing agreeing means the guess was wrong, not the hints:
    しんろう "groom" lands on 心労 and would otherwise become "anxiety/worry/fear".
    No entry, no judgement -- the hints are kept as they are.
    """
    if not entry or not entry.get("senses"):
        return hints
    senses = [s for s in entry["senses"].split("|") if s]
    exact = [_gloss_tokens(s, keep_parens=False) for s in senses]
    loose = [_gloss_tokens(s, keep_parens=True) for s in senses]

    def agrees(hint: str) -> bool:
        short = _gloss_tokens(hint, keep_parens=False)
        if short and any(len(short) == len(e) and all(map(_same_token, short, e)) for e in exact):
            return True
        words = [t for t in _gloss_tokens(hint, keep_parens=True) if t not in ARTICLES]
        if not words or all(t in FUNCTION_WORDS for t in words):
            return False
        return any(all(any(_same_token(t, u) for u in sense) for t in words) for sense in loose)

    kept = [h for h in hints if agrees(h)]
    return kept or (senses if trusted else hints)


# -------------------------------------------------------------------------- grading
class Grader:
    """Assigns (listed, level, source, matched) to a word.

    Tiers run most-trustworthy first. The first four mean "this is the listed word";
    the rest mean "this is not listed, but here is a defensible difficulty". The tier
    rules are generic; what counts as a token, a lemma or a heavy piece is the plugin's.
    `order` is the registry's levels, easiest first.
    """

    def __init__(self, tests: list[dict], lang, order: list[str]):
        self.lang = lang
        self.order = list(order)
        norm = lang.normalise
        self.by_expression: dict[str, list[dict]] = {}
        self.by_reading: dict[str, list[dict]] = {}
        self.by_folded: dict[str, list[dict]] = {}
        self.by_meaning: dict[str, list[dict]] = {}
        self.level = languages.Levels(self.order)
        for t in tests:
            if t.get("level") not in self.order:
                continue
            expression = norm(t["expression"])
            reading = norm(t["reading"]) if t.get("reading") else ""
            self.by_expression.setdefault(expression, []).append(t)
            if reading:
                self.by_reading.setdefault(reading, []).append(t)
            for key in dict.fromkeys(k for k in (fold(expression), fold(reading)) if k):
                self.by_folded.setdefault(key, []).append(t)
            for sense in self._senses(t.get("meaning", "")):
                self.by_meaning.setdefault(sense, []).append(t)
            for key in (expression, reading):
                if key:
                    prior = self.level.get(key)
                    if prior is None or self._easier(t["level"], prior):
                        self.level[key] = t["level"]

    def _easier(self, a: str, b: str) -> bool:
        return self.order.index(a) < self.order.index(b)

    @staticmethod
    def _senses(text: str) -> set[str]:
        out = set()
        for part in text.replace(";", ",").split(","):
            sense = part.strip().lower().removeprefix("to ").strip("() ")
            if sense:
                out.add(sense)
        return out

    def _pick(self, candidates: list[dict]) -> tuple[str, str]:
        """Easiest level, and a citation from an entry actually at that level."""
        level = min({c["level"] for c in candidates}, key=self.order.index)
        return level, next(c for c in candidates if c["level"] == level)["expression"]

    @staticmethod
    def _join(units: list[str], word: str) -> str:
        """Pieces are characters when the units concatenate back to the word, else words."""
        return "" if "".join(units) == word else " "

    def _decompose(self, word: str) -> list[str] | None:
        """Greedy longest-match split over the plugin's tokens.

        Japanese tokens kanji words only: kana strings segment into nonsense -- すし
        becomes す (vinegar) + し (death), たなか becomes たな + か. A single-token piece
        must carry weight >= 2 and be a content word, which keeps lone kana and lone
        articles from being "parts".
        """
        lang = self.lang
        units = lang.tokens(word)
        if not units:
            return None
        sep = self._join(units, word)
        parts, i = [], 0
        while i < len(units):
            for end in range(len(units), i, -1):
                piece = sep.join(units[i:end])
                if lang.normalise(piece) in self.level and (
                        end - i > 1 or (lang.weight(piece) >= 2 and lang.is_content(piece))):
                    parts.append(piece)
                    i = end
                    break
            else:
                return None
        return parts if len(parts) >= 2 else None

    def _contains(self, word: str) -> tuple[str, str] | None:
        """A listed word inside this one: アイスコーヒー -> コーヒー.

        Two guards, both needed. Without them サッカー inherits from カー ("car"),
        パスタ from パス, ファンタジー from ファン, と言います from ます, and カナダじん
        from じん -- none of which is a part of the word in any meaningful sense.

          weight >= 3   two kana is a syllable, not a word; 日本 clears it on kanji
          >= 55% cover  the piece must be most of the word, not a fragment of it

        Pieces are runs of the plugin's tokens (characters when it returns none), and a
        piece that is a bare particle or article never counts.
        """
        lang = self.lang
        units = lang.tokens(word) or list(word)
        sep = self._join(units, word)
        total = lang.weight(word)
        if total <= 0:
            return None
        best = None
        for size in range(len(units) - 1, 0, -1):
            for start in range(len(units) - size + 1):
                piece = sep.join(units[start:start + size])
                key = lang.normalise(piece)
                if key not in self.level:
                    continue
                weight = lang.weight(piece)
                if weight < 3 or weight / total < 0.55 or not lang.is_content(piece):
                    continue
                # Hardest wins: knowing the whole means knowing its most demanding part.
                if best is None or self._easier(self.level[best[0]], self.level[key]):
                    best = (key, piece)
            if best:
                return self.level[best[0]], best[1]
        return None

    def _stem(self, a: str, b: str) -> int:
        """Weight of the shared leading prefix (one kanji counting as much as two kana)."""
        norm = self.lang.normalise
        a, b = norm(a), norm(b)
        n = 0
        for x, y in zip(a, b):
            if x != y:
                break
            n += 1
        return self.lang.weight(a[:n]) if n else 0

    def grade(self, word: str, gloss: list[str], entry: dict | None) -> tuple[bool, str | None, str | None, str | None]:
        norm = self.lang.normalise
        key = norm(word)
        # --- listed: this exact lexeme is on a test list -------------------------
        if key in self.by_expression:
            level, via = self._pick(self.by_expression[key])
            return True, level, "expression", via
        if key in self.by_reading:
            level, via = self._pick(self.by_reading[key])
            return True, level, "reading", via
        if entry:
            # Written spellings only. Readings are homophone magnets -- JMdict lists
            # とうけい as an alternate reading of 東京, which lands on 統計.
            for form in (entry.get("forms") or "").split("|"):
                if form and form != word and norm(form) in self.by_expression:
                    level, via = self._pick(self.by_expression[norm(form)])
                    return True, level, "variant", via
        exact: list[dict] = []
        loose: list[dict] = []
        for form in self.lang.lemmas(word):
            f = norm(form)
            exact += self.by_expression.get(f, []) + self.by_reading.get(f, [])
            loose += self.by_folded.get(fold(f), [])
        seen = {id(c) for c in exact}
        inflected = exact + [c for c in loose if id(c) not in seen and not seen.add(id(c))]
        if inflected:
            # Meaning overlap and accent agreement are tie-breakers, never gates: gating
            # on meaning drops 学びます -> 学ぶ ("learns" vs "to learn; to study").
            wanted = content_words(" ".join(gloss or []))
            pool = [i for i in inflected if content_words(i.get("meaning", "")) & wanted] or inflected
            exact_ids = {id(c) for c in exact}
            pool = [c for c in pool if id(c) in exact_ids] or pool
            level, via = self._pick(pool)
            return True, level, "inflection", via

        # --- inferred: not listed, but gradeable ---------------------------------
        for candidate in (word, written(entry)):
            parts = self._decompose(candidate) if candidate else None
            if parts:
                # Hardest part: a compound is only readable once you know all of it.
                hardest = max((self.level[norm(p)] for p in parts), key=self.order.index)
                return False, hardest, "composite", "+".join(parts)

        stem_hits = []
        # Sorted: set order varies per process, and it decides which citation `matched` gets.
        for sense in sorted({g.strip().lower().removeprefix("to ") for g in gloss or []}):
            stem_hits += self.by_meaning.get(sense, [])
        corroborated = [
            c for c in stem_hits
            if max(self._stem(word, c["expression"]), self._stem(word, c.get("reading") or "")) >= 2
        ]
        if corroborated and len({c["level"] for c in corroborated}) == 1:
            level, via = self._pick(corroborated)
            return False, level, "stem", via

        for candidate in (word, written(entry)):
            found = self._contains(candidate) if candidate else None
            if found:
                return False, found[0], "contains", found[1]

        return False, None, None, None

    def rate_name(self, word: str) -> tuple[str | None, str | None]:
        """Names get a difficulty from the plugin (script-based), since no list carries them."""
        result = self.lang.name_rating(word, self.level)
        if result is None:
            return None, None
        if isinstance(result, tuple):
            return result[0], result[1]
        return result, "name"

    def rating(self, label: str | None) -> int | None:
        return languages.rating_of(label, self.order) if label else None


def looks_like_name(gloss: list[str]) -> bool:
    """A gloss whose every word is capitalised, e.g. 'Naomi', 'New York', 'J-pop'.

    Demonyms are excluded -- 'Japanese' is ordinary vocabulary, not a name.
    """
    if not gloss:
        return False
    for sense in gloss:
        tokens = [t for t in re.split(r"[\s\-]+", sense.strip()) if t]
        if not tokens:
            return False
        if any(t.lower() in DEMONYMS for t in tokens):
            return False
        if not all(t[0].isupper() or not t[0].isalpha() for t in tokens):
            return False
    return True


def course_rating(unit: int, order: list[str]) -> int:
    """Rating from course position alone -- not a test judgement, labelled as such."""
    index = min(sum(1 for band in COURSE_BANDS if unit > band), len(order) - 1)
    return len(order) - index


# ----------------------------------------------------------------------------- main
def canonical(word: str, entry: dict | None) -> str:
    """Dedup key. Two surfaces of one dictionary word collapse: おちゃ and お茶."""
    if entry:
        return f"{entry.get('headword') or ''}|{entry.get('reading') or ''}"
    return word


def load_existing(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    return {r["word"]: r for r in (json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip())}


def ordered(record: dict) -> dict:
    return {k: record[k] for k in FIELD_ORDER if k in record} | {k: v for k, v in record.items() if k not in FIELD_ORDER}


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as fh:
        for record in records:
            fh.write(json.dumps(ordered(record), ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def lexicon_path(code: str) -> Path:
    return languages.language_dir(PROFILE_DIR, code) / "lexicon.jsonl"


def names_path(code: str) -> Path:
    return languages.language_dir(PROFILE_DIR, code) / "names.jsonl"


def resolve_language(arg: str | None, dry_run: bool) -> str:
    """--language (a code or a registry name) wins and is written; else profile.json."""
    if arg:
        reg = languages.registry()
        code = arg if arg in reg else {v["name"].lower(): k for k, v in reg.items()}.get(arg.lower())
        if code is None:
            raise SystemExit(f"Unknown language {arg!r} -- supported: {', '.join(sorted(reg))}")
        return code
    return languages.active_code(PROFILE, write=not dry_run)


def int_or_none(value) -> int | None:
    value = (value or "").strip() if isinstance(value, str) else value
    try:
        return int(value) if value not in (None, "") else None
    except ValueError:
        return None


def main() -> None:
    global CONNECTIONS, RESOURCES
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--language", help="registry code (or name); switches profile.json to it")
    ap.add_argument("--through-unit", type=int, help="override every connection's course position")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--root", help="read Connections/ and Resources/ under this directory instead")
    args = ap.parse_args()
    if args.root:
        CONNECTIONS = Path(args.root) / "Connections"
        RESOURCES = Path(args.root) / "Resources"

    code = resolve_language(args.language, args.dry_run)
    spec = languages.spec(code)
    lang = languages.plugin(code)
    order = languages.levels(code)
    if not order:
        raise SystemExit(f"languages.json gives {code} no test levels")
    name = spec["name"]

    lexicon_file, names_file = lexicon_path(code), names_path(code)
    previous_files = [lexicon_file, names_file]
    if args.dry_run:
        if code == languages.DEFAULT and not lexicon_file.parent.exists():
            previous_files = [PROFILE_DIR / "lexicon.jsonl", PROFILE_DIR / "names.jsonl"]
    else:
        moved = languages.migrate_flat(PROFILE_DIR, code)
        if moved:
            print(f"moved {', '.join(moved)} into {rel(lexicon_file.parent)}/")

    tables = language_files(name)
    if not tables:
        raise SystemExit(f"No {name} word table under {rel(CONNECTIONS)}/*/data/languages/*/{name.lower()}.csv -- "
                         "run  python setup.py  from the project root (or type /setup in Claude Code).")

    # Per connection: its course entry and position. A connection without units (Anki)
    # contributes no position.
    connections: dict[str, dict] = {}
    rows_by_connection: list[tuple[str, list[dict]]] = []
    for folder, path in tables:
        rows = read_csv(path)
        has_units = any(int_or_none(r.get("unit")) is not None for r in rows)
        course = read_course(path, code)
        through = None
        if has_units:
            through = args.through_unit if args.through_unit is not None else course.get("through_unit")
        info = connections.setdefault(folder, {"course": course, "through_unit": None, "has_units": False})
        info["has_units"] |= has_units
        if through is not None:
            info["through_unit"] = through if info["through_unit"] is None else max(info["through_unit"], through)
        rows_by_connection.append((folder, rows))
    through_of = {folder.lower(): info["through_unit"] for folder, info in connections.items()}

    dictionary = index_dictionary(load_dictionary(name, (spec.get("dictionary") or {}).get("source")), lang)
    tests = load_tests(name, (spec.get("tests") or {}).get("source"), order)
    grader = Grader(tests, lang, order)
    today = date.today().isoformat()
    norm = lang.normalise

    # Learner evidence keyed by surface form, carried across the rebuild.
    previous = load_existing(previous_files[0]) | load_existing(previous_files[1])

    records: dict[str, dict] = {}          # canonical key -> record
    connection_tags = {folder.lower() for folder, _ in tables}

    def upsert(word: str, gloss: list[str], source: str, extra: dict) -> dict:
        # The raw hints pick the entry -- the cleaning needs an entry to clean against.
        entry = best_entry(word, gloss, dictionary, lang) if dictionary else None
        key = canonical(word, entry)
        record = records.get(key)
        hints = gloss
        if source in connection_tags and entry:
            # Only a connection's gloss is a union of hints; a test row's meaning is
            # written for that one entry and has nothing to strip.
            trusted = len(dictionary[norm(word)]) == 1 or bool(
                content_words(" ".join(gloss)) & content_words(entry["senses"].replace("|", " ")))
            gloss = clean_gloss(gloss, entry, trusted)
        if record is None:
            # Grading sees the cleaned gloss, so the stem tier cannot match on a
            # homophone's hint ("door" for と).
            listed, level, how, via = grader.grade(word, gloss, entry)
            record = {
                "word": word,
                **lang.fields(word, entry),
                "romaji": None,
                "gloss": gloss,
                "hints": hints,
                "pos": ((entry.get("pos") or "").split("|") if entry and entry.get("pos") else []),
                "script": lang.script_of(word),
                "variants": [f for f in (((entry.get("forms") or "") + "|" + (entry.get("readings") or "")).split("|")
                                         if entry else []) if f and f != word],
                "listed": listed,
                "rating": grader.rating(level),
                "rating_source": how,
                "matched": via,
                "sources": [],
                "language": name,
            }
            records[key] = record
        if source not in record["sources"]:
            record["sources"].append(source)
        # A word the course teaches keeps the course's metadata; test-only words have none.
        # Two spellings of one word (おちゃ in unit 1, お茶 in unit 66) are one record, and
        # the EARLIEST unit is when it was taught -- letting the last row win put おちゃ at
        # unit 66 and locked it out of chat. Every other unit becomes a repeat.
        if extra.get("unit") is not None:
            earlier = record.get("unit") is None or extra["unit"] < record["unit"]
            units = set(record.get("repeat_units") or []) | set(extra.get("repeat_units") or [])
            units |= {u for u in (record.get("unit"), extra["unit"]) if u is not None}
            for field, value in extra.items():
                if field == "repeat_units" or value is None:
                    continue
                if earlier or record.get(field) is None:
                    record[field] = value
            if earlier:
                record["_unit_from"] = source
            record["repeat_units"] = sorted(units - {record["unit"]})
        else:
            # No unit (Anki, tests): fill blanks only, never displace a course's metadata.
            for field, value in extra.items():
                if value is not None and record.get(field) is None and field not in ("unit", "repeat_units"):
                    record[field] = value
        if not record["gloss"]:
            record["gloss"] = gloss
        return record

    # 1. Connection words -- unit position, audio, and the learner's exposure.
    for folder, rows in rows_by_connection:
        tag = folder.lower()
        for row in rows:
            word = (row.get("word") or "").strip()
            if not word:
                continue
            gloss = [g for g in (row.get("gloss") or "").split("|") if g]
            unit = int_or_none(row.get("unit"))
            extra = {"romaji": row.get("reading") or None, "audio": row.get("audio") or None}
            if unit is not None:
                extra = {
                    "romaji": row.get("reading") or None,
                    "unit": unit,
                    "unit_name": row.get("unit_name") or "",
                    "unit_topic": row.get("unit_topic") or "",
                    "repeat_units": [int(u) for u in (row.get("repeat_units") or "").split("|") if u.strip().isdigit()],
                    "audio": row.get("audio") or None,
                }
            record = upsert(word, gloss, tag, extra)
            if (row.get("seen") or "").strip() == "1":
                record["seen"] = True

    # 2. Test words no connection has -- still worth knowing they exist.
    for t in tests:
        gloss = [g.strip() for g in t["meaning"].replace(";", ",").split(",") if g.strip()]
        upsert(t["expression"], gloss, "tests", {})

    # 3. Split names out, and restore learner evidence by surface form.
    lexicon, names = [], []
    for record in records.values():
        unit_from = record.pop("_unit_from", None)
        # Names are judged on the raw hints: a cleaned gloss can fall back to dictionary
        # senses, and "rice paddy" would turn たなか back into vocabulary.
        name_like = looks_like_name(record["hints"] or record["gloss"]) and not record["listed"]
        # Raw hints are kept only where cleaning dropped something -- that is the record
        # of what was stripped, and everywhere else it would just repeat the gloss.
        if record["hints"] == record["gloss"]:
            del record["hints"]
        if name_like and record["rating"] is None:
            level, how = grader.rate_name(record["word"])
            if level:
                record["rating"], record["rating_source"] = grader.rating(level), how

        # Last resort: where the course introduced it. Not a test judgement at all --
        # just the only difficulty signal left for loanwords the test lists ignore
        # (ピザ, コンビニ, スマホ). Monotonic in course order, and labelled as such.
        if record["rating"] is None and record.get("unit"):
            record["rating"] = course_rating(record["unit"], order)
            record["rating_source"] = "course-position"

        through = through_of.get(unit_from) if unit_from else None
        reached = (through is not None and record.get("unit") is not None and record["unit"] <= through) \
            or bool(record.get("seen"))
        prior = previous.get(record["word"])
        record["confidence"] = (prior or {}).get("confidence")
        if record["confidence"] is None:
            record["confidence"] = "exposed" if reached else "unseen"
        elif record["confidence"] == "unseen" and reached:
            record["confidence"] = "exposed"
        record["seen_count"] = (prior or {}).get("seen_count", 0)
        record["first_seen"] = (prior or {}).get("first_seen", today)
        if (prior or {}).get("last_seen"):
            record["last_seen"] = prior["last_seen"]
        record["srs"] = (prior or {}).get("srs")

        (names if name_like else lexicon).append(record)

    lexicon.sort(key=lambda r: (r.get("unit") or 10**6, -(r.get("rating") or 0), r["word"]))
    names.sort(key=lambda r: (r.get("unit") or 10**6, r["word"]))

    # ------------------------------------------------------------------ reporting
    graded = [r for r in lexicon if r["rating"]]
    listed = [r for r in lexicon if r["listed"]]
    by_source = Counter(r["rating_source"] for r in lexicon if r["rating_source"])
    by_origin = Counter(tuple(sorted(r["sources"])) for r in lexicon)
    positions = {f: i["through_unit"] for f, i in connections.items() if i["has_units"]}
    position_text = ", ".join(f"{f} unit {u}" for f, u in positions.items()) or "none (no unit-gated connection)"

    print(f"{name} ({code}) -- course position: {position_text}")
    print(f"  lexicon {len(lexicon):,}  ·  names {len(names):,}")
    for origin, count in by_origin.most_common():
        print(f"      {'+'.join(origin):<18} {count:>6,}")
    print(f"  graded {len(graded):,}/{len(lexicon):,} ({100*len(graded)/max(len(lexicon),1):.0f}%)"
          f"  ·  on a test list {len(listed):,} ({100*len(listed)/max(len(lexicon),1):.0f}%)")
    print("      " + ", ".join(f"{k}={v}" for k, v in by_source.most_common()))
    ratings = Counter(r["rating"] for r in lexicon if r["rating"])
    print("      " + " · ".join(f"{label}={ratings.get(languages.rating_of(label, order), 0)}" for label in order))
    fields = list(lang.fields("", None))
    print("  " + "  ·  ".join(f"{f} {sum(1 for r in lexicon if r.get(f)):,}" for f in fields)
          + f"  ·  variants {sum(1 for r in lexicon if r['variants']):,}")
    # Same rule as `lexicon.py stats`: unlocked, and an `exposed` word not past the
    # furthest course position -- what chat actually receives.
    furthest = max((u for u in positions.values() if u is not None), default=None)
    usable = sum(1 for r in lexicon if r["confidence"] != "unseen"
                 and (r["confidence"] != "exposed" or furthest is None or r.get("seen")
                      or (r.get("unit") or 0) <= furthest))
    print(f"  usable for chat: {usable:,}")

    if args.dry_run:
        print("dry run -- nothing written")
        return

    write_jsonl(lexicon_file, lexicon)
    write_jsonl(names_file, names)

    profile = json.loads(PROFILE.read_text(encoding="utf-8")) if PROFILE.exists() else {}
    if profile.get("language") not in (code, name):
        profile["connections"] = {}  # positions belong to the language they were built for
    profile["language"] = code
    profile["updated"] = today
    profile.setdefault("connections", {})
    for folder, info in connections.items():
        course = info["course"]
        profile["connections"][folder] = {
            "course": f"{course.get('from_language', '?')}-{course.get('learning_language', '?')}" if course else None,
            "through_unit": info["through_unit"],
        }
    profile["lexicon"] = {
        "total": len(lexicon), "names": len(names), "usable": usable,
        "graded": len(graded), "on_test_list": len(listed),
        **{k: sum(1 for r in lexicon if r["confidence"] == k) for k in ("unseen", "exposed", "shaky", "known")},
    }
    PROFILE.parent.mkdir(parents=True, exist_ok=True)
    PROFILE.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {rel(lexicon_file)}, {rel(names_file)} and {rel(PROFILE)}")


if __name__ == "__main__":
    main()
