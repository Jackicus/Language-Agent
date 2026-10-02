#!/usr/bin/env python3
"""Build Profile/lexicon.jsonl from the connections and resources.

    Connections/  what YOU did          -> Duolingo course words, in course order
    Resources/    reference material    -> JLPT test lists, JMdict dictionary
    Profile/      what the lexicon is   -> the merged word store, plus your evidence

The lexicon is the union of the course words and the test words, deduplicated on the
dictionary entry they resolve to (so おちゃ and お茶 are one record, not two). JMdict
fills in whatever the other two leave blank -- readings above all, since Duolingo gives
none at all for kanji-only entries.

Two grading fields, deliberately separate:

    jlpt    bool -- is this exact word actually in a test list?
    rating  1-5  -- how hard is it, 5 being N5 (easiest) and 1 being N1

コーヒー is `jlpt: true, rating: 5` because it is listed. アイスコーヒー is
`jlpt: false, rating: 5` -- not listed, but it contains コーヒー and cannot be harder
than its parts. Keeping the two apart means exam coverage stays honest while every word
still gets a usable difficulty.

Proper nouns go to Profile/names.jsonl instead. たなか and トロント are not vocabulary,
and leaving them in the lexicon would let /chat "use words you know" to mean reciting
place names.

Usage:
    python build_lexicon.py
    python build_lexicon.py --language Japanese
    python build_lexicon.py --through-unit 20
    python build_lexicon.py --dry-run
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
from collections import Counter
from datetime import date
from pathlib import Path

PROFILE_DIR = Path(__file__).resolve().parents[2]
ROOT = PROFILE_DIR.parent
CONNECTIONS = ROOT / "Connections"
RESOURCES = ROOT / "Resources"
LEXICON = PROFILE_DIR / "lexicon.jsonl"
NAMES = PROFILE_DIR / "names.jsonl"
PROFILE = PROFILE_DIR / "profile.json"

# Everything a connection or resource owns, refreshed on every build.
DERIVED = ("kana", "kanji", "romaji", "gloss", "hints", "pos", "script", "variants", "jlpt", "rating",
           "rating_source", "matched", "sources", "unit", "unit_name", "unit_topic",
           "repeat_units", "audio", "language")
# Learner evidence. Never overwritten.
LEARNER = ("confidence", "seen_count", "srs", "first_seen", "last_seen")

# The order fields appear in the JSONL, so a record reads sensibly.
FIELD_ORDER = ["word", "kana", "kanji", "romaji", "gloss", "hints", "pos", "script", "variants",
               "jlpt", "rating", "rating_source", "matched",
               "sources", "unit", "unit_name", "unit_topic", "repeat_units", "audio",
               "language", "confidence", "seen_count", "first_seen", "last_seen", "srs"]

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

GODAN_STEM = {"い": "う", "き": "く", "ぎ": "ぐ", "し": "す", "ち": "つ",
              "に": "ぬ", "び": "ぶ", "み": "む", "り": "る"}
POLITE_SUFFIXES = ("ませんでした", "ましょう", "ません", "ました", "ます")
# Every polite ending the regular rule handles, for both irregulars -- a gap falls through
# to the regular rule, and しましょう becomes しる and hits 知る, きましょう hits 着る.
IRREGULAR = {stem + suffix: [plain] for stem, plain in (("し", "する"), ("き", "来る"))
             for suffix in POLITE_SUFFIXES}


# --------------------------------------------------------------------------- helpers
def content_words(text: str) -> set[str]:
    return {w for w in re.split(r"[^a-z']+", text.lower()) if w and w not in STOPWORDS}


def is_kanji(ch: str) -> bool:
    return "CJK UNIFIED" in unicodedata.name(ch, "")


def has_kanji(text: str) -> bool:
    return any(is_kanji(ch) for ch in text)


def is_kana(text: str) -> bool:
    return bool(text) and all(
        "HIRAGANA" in unicodedata.name(ch, "") or "KATAKANA" in unicodedata.name(ch, "") or ch in "ー・っッ"
        for ch in text
    )


def script_of(word: str) -> str:
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


def level_num(level: str) -> int:
    """N5 -> 5. Bigger is easier."""
    return int(level[1:])


# ------------------------------------------------------------------------ loading
def find_wordlist(preferred: str | None) -> tuple[str, Path]:
    candidates = sorted(CONNECTIONS.glob("*/data/languages/*/*.csv"))
    if not candidates:
        raise SystemExit("No course word table -- run  python setup.py  from the project root (or type /setup in Claude Code).")
    if preferred:
        for path in candidates:
            if path.stem.lower() == preferred.lower():
                return path.stem.capitalize(), path
        raise SystemExit(f"No word table for {preferred!r}")
    if len(candidates) > 1:
        raise SystemExit(f"Several languages present -- pass --language")
    return candidates[0].stem.capitalize(), candidates[0]


def read_course(wordlist: Path) -> dict:
    connection_root = wordlist.parents[3]
    path = connection_root / "profile.json"
    if not path.exists():
        return {}
    profile = json.loads(path.read_text(encoding="utf-8"))
    wanted = wordlist.relative_to(connection_root).as_posix()
    for course in profile.get("courses", {}).values():
        if course.get("wordlist") == wanted:
            return course
    return {}


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def load_tests(language: str) -> list[dict]:
    folder = RESOURCES / "Tests" / language
    rows = []
    if folder.exists():
        for path in sorted(folder.glob("*.csv")):
            rows += [r for r in read_csv(path) if r.get("expression")]
    return rows


def load_dictionary(language: str) -> list[dict]:
    return read_csv(RESOURCES / "Dictionary" / language / "jmdict.csv")


# --------------------------------------------------------------------- dictionary
def index_dictionary(entries: list[dict]) -> dict[str, list[dict]]:
    """Surface form -> entries. A list, because 時 belongs to both とき and (rarely) 秋."""
    index: dict[str, list[dict]] = {}
    for entry in entries:
        for form in entry["kanji_all"].split("|") + entry["kana_all"].split("|"):
            if form:
                index.setdefault(form, []).append(entry)
    return index


def best_entry(word: str, gloss: list[str], index: dict[str, list[dict]]) -> dict | None:
    """The entry that means what the source said it means.

    Without the sense check 本 resolves to もと rather than ほん, and が to 絵.
    """
    candidates = index.get(word)
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
        grammatical = [c for c in candidates if word in (c["kana"], c["kanji"])
                       and any(p in ("prt", "conj", "cop") or p.startswith("aux") for p in c["pos"].split("|"))]
        if grammatical:
            return grammatical[0]
    wanted = content_words(" ".join(gloss or []))

    def score(entry: dict) -> tuple[int, int]:
        return (len(content_words(entry.get("senses", "").replace("|", " ")) & wanted),
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
    """Assigns (jlpt, rating, source, matched) to a word.

    Tiers run most-trustworthy first. The first four mean "this is the listed word";
    the rest mean "this is not listed, but here is a defensible difficulty".
    """

    def __init__(self, tests: list[dict]):
        self.by_expression: dict[str, list[dict]] = {}
        self.by_reading: dict[str, list[dict]] = {}
        self.by_meaning: dict[str, list[dict]] = {}
        self.level: dict[str, str] = {}
        for t in tests:
            self.by_expression.setdefault(t["expression"], []).append(t)
            if t.get("reading"):
                self.by_reading.setdefault(t["reading"], []).append(t)
            for sense in self._senses(t.get("meaning", "")):
                self.by_meaning.setdefault(sense, []).append(t)
            for key in (t["expression"], t.get("reading")):
                if key:
                    prior = self.level.get(key)
                    if prior is None or level_num(t["level"]) > level_num(prior):
                        self.level[key] = t["level"]

    @staticmethod
    def _senses(text: str) -> set[str]:
        out = set()
        for part in text.replace(";", ",").split(","):
            sense = part.strip().lower().removeprefix("to ").strip("() ")
            if sense:
                out.add(sense)
        return out

    @staticmethod
    def _pick(candidates: list[dict]) -> tuple[str, str]:
        """Easiest level, and a citation from an entry actually at that level."""
        level = max({c["level"] for c in candidates}, key=level_num)
        return level, next(c for c in candidates if c["level"] == level)["expression"]

    def _dictionary_forms(self, word: str) -> list[str]:
        if word in IRREGULAR:
            return IRREGULAR[word]
        for suffix in POLITE_SUFFIXES:
            if word.endswith(suffix) and len(word) > len(suffix):
                stem = word[: -len(suffix)]
                forms = [stem + "る"]
                if stem[-1] in GODAN_STEM:
                    forms.append(stem[:-1] + GODAN_STEM[stem[-1]])
                return [f for f in forms if len(f) >= 2]
        return []

    def _decompose(self, word: str) -> list[str] | None:
        """Greedy longest-match split, kanji only.

        Kana strings segment into nonsense: すし becomes す (vinegar) + し (death),
        たなか becomes たな + か. Kanji carries enough per character to be meaningful.
        """
        if not has_kanji(word):
            return None
        parts, i = [], 0
        while i < len(word):
            for end in range(len(word), i, -1):
                piece = word[i:end]
                if piece in self.level and (len(piece) > 1 or not is_kana(piece)):
                    parts.append(piece)
                    i = end
                    break
            else:
                return None
        return parts if len(parts) >= 2 else None

    @staticmethod
    def _weight(text: str) -> int:
        """Information content: a kanji is worth two kana, since there are far more."""
        return sum(2 if is_kanji(ch) else 1 for ch in text)

    def _contains(self, word: str) -> tuple[str, str] | None:
        """A listed word inside this one: アイスコーヒー -> コーヒー.

        Two guards, both needed. Without them サッカー inherits from カー ("car"),
        パスタ from パス, ファンタジー from ファン, と言います from ます, and カナダじん
        from じん -- none of which is a part of the word in any meaningful sense.

          weight >= 3   two kana is a syllable, not a word; 日本 clears it on kanji
          >= 55% cover  the piece must be most of the word, not a fragment of it
        """
        best = None
        for size in range(len(word) - 1, 1, -1):
            for start in range(len(word) - size + 1):
                piece = word[start:start + size]
                if piece not in self.level:
                    continue
                if self._weight(piece) < 3 or self._weight(piece) / self._weight(word) < 0.55:
                    continue
                # Hardest wins: knowing the whole means knowing its most demanding part.
                if best is None or level_num(self.level[piece]) < level_num(self.level[best]):
                    best = piece
            if best:
                return self.level[best], best
        return None

    def grade(self, word: str, gloss: list[str], entry: dict | None) -> tuple[bool, str | None, str | None, str | None]:
        # --- listed: this exact lexeme is on a test list -------------------------
        if word in self.by_expression:
            level, via = self._pick(self.by_expression[word])
            return True, level, "expression", via
        if word in self.by_reading:
            level, via = self._pick(self.by_reading[word])
            return True, level, "reading", via
        if entry:
            # Kanji spellings only. Kana readings are homophone magnets -- JMdict lists
            # とうけい as an alternate reading of 東京, which lands on 統計.
            for form in entry["kanji_all"].split("|"):
                if form and form != word and form in self.by_expression:
                    level, via = self._pick(self.by_expression[form])
                    return True, level, "variant", via
        inflected = []
        for form in self._dictionary_forms(word):
            inflected += self.by_expression.get(form, []) + self.by_reading.get(form, [])
        if inflected:
            wanted = content_words(" ".join(gloss or []))
            agreeing = [i for i in inflected if content_words(i.get("meaning", "")) & wanted]
            level, via = self._pick(agreeing or inflected)
            return True, level, "inflection", via

        # --- inferred: not listed, but gradeable ---------------------------------
        for candidate in (word, (entry or {}).get("kanji")):
            parts = self._decompose(candidate) if candidate else None
            if parts:
                # Hardest part: a compound is only readable once you know all of it.
                hardest = min((self.level[p] for p in parts), key=level_num)
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

        for candidate in (word, (entry or {}).get("kanji")):
            found = self._contains(candidate) if candidate else None
            if found:
                return False, found[0], "contains", found[1]

        return False, None, None, None

    @staticmethod
    def _stem(a: str, b: str) -> int:
        score = 0
        for x, y in zip(a, b):
            if x != y:
                break
            score += 2 if is_kanji(x) else 1
        return score

    def rate_name(self, word: str) -> tuple[str, str]:
        """Names get a difficulty from their script, since no list will carry them.

        Kanji names are as hard as their hardest character; short kana names are easy.
        """
        kanji_levels = [self.level[ch] for ch in word if is_kanji(ch) and ch in self.level]
        if kanji_levels:
            return min(kanji_levels, key=level_num), "name-kanji"
        if has_kanji(word):
            # Kanji we cannot place at all is not beginner material.
            return "N1", "name-kanji"
        return ("N5" if len(word) <= 4 else "N4"), "name-kana"


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


# ----------------------------------------------------------------------------- main
def canonical(word: str, entry: dict | None) -> str:
    """Dedup key. Two surfaces of one dictionary word collapse: おちゃ and お茶."""
    if entry:
        return f"{entry['kanji']}|{entry['kana']}"
    return word


def load_existing(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    return {r["word"]: r for r in (json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip())}


def ordered(record: dict) -> dict:
    return {k: record[k] for k in FIELD_ORDER if k in record} | {k: v for k, v in record.items() if k not in FIELD_ORDER}


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for record in records:
            fh.write(json.dumps(ordered(record), ensure_ascii=False) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--language")
    ap.add_argument("--through-unit", type=int)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    language, wordlist = find_wordlist(args.language)
    connection = wordlist.relative_to(CONNECTIONS).parts[0].lower()
    course = read_course(wordlist)
    through = args.through_unit if args.through_unit is not None else course.get("through_unit")

    dictionary = index_dictionary(load_dictionary(language))
    tests = load_tests(language)
    grader = Grader(tests)
    today = date.today().isoformat()

    # Learner evidence keyed by surface form, carried across the rebuild.
    previous = load_existing(LEXICON) | load_existing(NAMES)

    records: dict[str, dict] = {}          # canonical key -> record

    def upsert(word: str, gloss: list[str], source: str, extra: dict) -> dict:
        # The raw hints pick the entry -- the cleaning needs an entry to clean against.
        entry = best_entry(word, gloss, dictionary) if dictionary else None
        key = canonical(word, entry)
        record = records.get(key)
        hints = gloss
        if source == connection and entry:
            # Only the course's gloss is a union of hints; a test row's meaning is
            # written for that one entry and has nothing to strip.
            trusted = len(dictionary[word]) == 1 or bool(
                content_words(" ".join(gloss)) & content_words(entry["senses"].replace("|", " ")))
            gloss = clean_gloss(gloss, entry, trusted)
        if record is None:
            # Grading sees the cleaned gloss, so the stem tier cannot match on a
            # homophone's hint ("door" for と).
            jlpt, level, how, via = grader.grade(word, gloss, entry)
            record = {
                "word": word,
                "kana": (entry or {}).get("kana") or (word if is_kana(word) else None),
                "kanji": (entry or {}).get("kanji") or (word if has_kanji(word) else None),
                "romaji": None,
                "gloss": gloss,
                "hints": hints,
                "pos": (entry["pos"].split("|") if entry and entry["pos"] else []),
                "script": script_of(word),
                "variants": [f for f in ((entry["kanji_all"] + "|" + entry["kana_all"]).split("|") if entry else [])
                             if f and f != word],
                "jlpt": jlpt,
                "rating": level_num(level) if level else None,
                "rating_source": how,
                "matched": via,
                "sources": [],
                "language": language,
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
            record["repeat_units"] = sorted(units - {record["unit"]})
        if not record["gloss"]:
            record["gloss"] = gloss
        return record

    # 1. Course words -- these carry unit position, audio and the learner's exposure.
    for row in read_csv(wordlist):
        gloss = [g for g in row["gloss"].split("|") if g]
        upsert(row["word"], gloss, connection, {
            "romaji": row["reading"] or None,
            "unit": int(row["unit"]),
            "unit_name": row["unit_name"],
            "unit_topic": row["unit_topic"],
            "repeat_units": [int(u) for u in row["repeat_units"].split("|") if u],
            "audio": row["audio"] or None,
        })

    # 2. Test words the course never teaches -- still worth knowing they exist.
    for t in tests:
        gloss = [g.strip() for g in t["meaning"].replace(";", ",").split(",") if g.strip()]
        upsert(t["expression"], gloss, "tests", {})

    # 3. Split names out, and restore learner evidence by surface form.
    lexicon, names = [], []
    for record in records.values():
        # Names are judged on the raw hints: a cleaned gloss can fall back to dictionary
        # senses, and "rice paddy" would turn たなか back into vocabulary.
        name = looks_like_name(record["hints"] or record["gloss"]) and not record["jlpt"]
        # Raw hints are kept only where cleaning dropped something -- that is the record
        # of what was stripped, and everywhere else it would just repeat the gloss.
        if record["hints"] == record["gloss"]:
            del record["hints"]
        if name and record["rating"] is None:
            level, how = grader.rate_name(record["word"])
            record["rating"], record["rating_source"] = level_num(level), how

        # Last resort: where the course introduced it. Not a JLPT judgement at all --
        # just the only difficulty signal left for loanwords the test lists ignore
        # (ピザ, コンビニ, スマホ). Monotonic in course order, and labelled as such.
        if record["rating"] is None and record.get("unit"):
            unit = record["unit"]
            record["rating"] = 5 if unit <= 100 else 4 if unit <= 250 else 3 if unit <= 500 else 2 if unit <= 800 else 1
            record["rating_source"] = "course-position"

        prior = previous.get(record["word"])
        record["confidence"] = (prior or {}).get("confidence")
        if record["confidence"] is None:
            reached = through is not None and record.get("unit") is not None and record["unit"] <= through
            record["confidence"] = "exposed" if reached else "unseen"
        elif record["confidence"] == "unseen":
            reached = through is not None and record.get("unit") is not None and record["unit"] <= through
            if reached:
                record["confidence"] = "exposed"
        record["seen_count"] = (prior or {}).get("seen_count", 0)
        record["first_seen"] = (prior or {}).get("first_seen", today)
        if (prior or {}).get("last_seen"):
            record["last_seen"] = prior["last_seen"]
        record["srs"] = (prior or {}).get("srs")

        (names if name else lexicon).append(record)

    lexicon.sort(key=lambda r: (r.get("unit") or 10**6, -(r.get("rating") or 0), r["word"]))
    names.sort(key=lambda r: (r.get("unit") or 10**6, r["word"]))

    # ------------------------------------------------------------------ reporting
    graded = [r for r in lexicon if r["rating"]]
    listed = [r for r in lexicon if r["jlpt"]]
    by_source = Counter(r["rating_source"] for r in lexicon if r["rating_source"])
    by_origin = Counter(tuple(sorted(r["sources"])) for r in lexicon)

    print(f"{language} -- course position: unit {through}")
    print(f"  lexicon {len(lexicon):,}  ·  names {len(names):,}")
    for origin, count in by_origin.most_common():
        print(f"      {'+'.join(origin):<18} {count:>6,}")
    print(f"  graded {len(graded):,}/{len(lexicon):,} ({100*len(graded)/max(len(lexicon),1):.0f}%)"
          f"  ·  on a test list {len(listed):,} ({100*len(listed)/max(len(lexicon),1):.0f}%)")
    print("      " + ", ".join(f"{k}={v}" for k, v in by_source.most_common()))
    ratings = Counter(r["rating"] for r in lexicon if r["rating"])
    print("      " + " · ".join(f"N{n}={ratings.get(n, 0)}" for n in (5, 4, 3, 2, 1)))
    print(f"  kana {sum(1 for r in lexicon if r['kana']):,} ({100*sum(1 for r in lexicon if r['kana'])/max(len(lexicon),1):.0f}%)"
          f"  ·  kanji {sum(1 for r in lexicon if r['kanji']):,}"
          f"  ·  variants {sum(1 for r in lexicon if r['variants']):,}")
    # Same rule as `lexicon.py stats`: unlocked, and not past the course position --
    # what chat actually receives, not every word ever unlocked.
    usable = sum(1 for r in lexicon if r["confidence"] != "unseen"
                 and (through is None or (r.get("unit") or 0) <= through))
    print(f"  usable for chat: {usable:,}")

    if args.dry_run:
        print("dry run -- nothing written")
        return

    write_jsonl(LEXICON, lexicon)
    write_jsonl(NAMES, names)

    profile = json.loads(PROFILE.read_text(encoding="utf-8")) if PROFILE.exists() else {}
    profile["language"] = language
    profile["updated"] = today
    profile.setdefault("connections", {})[connection.capitalize()] = {
        "course": f"{course.get('from_language', '?')}-{course.get('learning_language', '?')}",
        "through_unit": through,
    }
    profile["lexicon"] = {
        "total": len(lexicon), "names": len(names), "usable": usable,
        "graded": len(graded), "on_test_list": len(listed),
        **{k: sum(1 for r in lexicon if r["confidence"] == k) for k in ("unseen", "exposed", "shaky", "known")},
    }
    PROFILE.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {LEXICON.relative_to(ROOT)}, {NAMES.relative_to(ROOT)} and {PROFILE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
