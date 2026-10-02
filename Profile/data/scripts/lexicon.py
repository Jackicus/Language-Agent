#!/usr/bin/env python3
"""Query and update Profile/<code>/lexicon.jsonl for the active language.

The lexicon is far too large to paste into a prompt, so the chat skill talks to it
through this script instead of reading the file. Everything prints JSON on stdout
except the --compact views, which print one word per line for pasting into a prompt.

The active language is Profile/profile.json["language"] (a key of languages.json;
missing -> "ja", written back). Labels, readings, scripts and test levels come from the
registry and the language's plugin in languages/.

Run from Profile/data/scripts/:

    python lexicon.py stats
    python lexicon.py vocab --through-unit 95        # words available for chat
    python lexicon.py vocab --through-unit 95 --compact
    python lexicon.py set-unit 95                    # record course position by hand
    python lexicon.py mark 食べる known そうです shaky   # kanji, kana or any variant
    python lexicon.py look 食べる
    python lexicon.py quiz --count 8 [--only due|shaky|new] [--direction jp2en|en2jp]
    python lexicon.py tests                          # coverage per registry test level
    python lexicon.py review [--all] [--compact]     # words the schedule says are due

Confidence ladder:
    unseen   -- the course has not reached this word yet; chat must not use it
    exposed  -- the course introduced it; chat may use it
    shaky    -- learner hesitated or got it wrong; chat should reuse it deliberately
    known    -- learner used or recognised it unprompted

Review schedule (the `srs` field, Leitner boxes):
    srs is null until a word is first marked shaky or known, then
    {"box": 1-6, "due": "YYYY-MM-DD", "last": "YYYY-MM-DD"}; box n waits 2**(n-1) days.
    shaky -> box 1 (due tomorrow).  known -> up one box, null counting as box 1, but
    only when the word was due -- an early correct answer keeps its box and due date.
    exposed and unseen leave srs untouched.

Environment:
    LEXICON_DIR    directory holding profile.json and <code>/lexicon.jsonl, <code>/names.jsonl
                   (default: Profile/) -- point it at a copy for tests and dry runs
    LEXICON_TODAY  YYYY-MM-DD to use as "today" for scheduling (default: the real date)
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
from datetime import date, timedelta
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
import languages  # noqa: E402

# scripts live at Profile/data/scripts/, so Profile is three up.
PROFILE_DIR = Path(os.environ.get("LEXICON_DIR") or Path(__file__).resolve().parents[2])
ROOT = Path(__file__).resolve().parents[3]
PROFILE = PROFILE_DIR / "profile.json"

# Windows consoles default to cp1252, which cannot encode Japanese -- every command
# here prints Japanese, so force UTF-8 rather than crash on the first kanji.
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")

LEVELS = ("unseen", "exposed", "shaky", "known")
# Words chat is allowed to produce. "unseen" is deliberately excluded.
USABLE = ("exposed", "shaky", "known")

# Leitner intervals in days, indexed by box - 1.
INTERVALS = (1, 2, 4, 8, 16, 32)



def today() -> str:
    return os.environ.get("LEXICON_TODAY") or date.today().isoformat()


_code_cache: dict = {}


def code() -> str:
    """The active language code (CONTRACTS section 1). Cached per profile.json version,
    since stats asks for it once per record."""
    try:
        stamp = PROFILE.stat().st_mtime_ns
    except OSError:
        stamp = None
    key = (str(PROFILE), stamp)
    if key not in _code_cache:
        _code_cache.clear()
        result = languages.active_code(PROFILE)
        try:  # active_code may have just written the file: cache under its new stamp
            key = (str(PROFILE), PROFILE.stat().st_mtime_ns)
        except OSError:
            pass
        _code_cache[key] = result
        return result
    return _code_cache[key]


def lang():
    """The active language's plugin."""
    return languages.plugin(code())


def level_order() -> list[str]:
    """Registry test levels, easiest first: rating = len(levels) - index."""
    return languages.levels(code())


def level_label(rating) -> str | None:
    """5 -> "N5" for Japanese, 6 -> "A1" for a CEFR language."""
    return languages.label_of(rating, level_order())


def lexicon_path() -> Path:
    return languages.language_dir(PROFILE_DIR, code()) / "lexicon.jsonl"


def names_path() -> Path:
    return languages.language_dir(PROFILE_DIR, code()) / "names.jsonl"


def load() -> list[dict]:
    # The pre-registry flat layout moves into Profile/ja/ on first touch, as the build does.
    languages.migrate_flat(PROFILE_DIR, code())
    path = lexicon_path()
    if not path.exists():
        sys.exit(f"{path} not found -- run  python setup.py  from the project root (or type /setup in Claude Code).")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def save(records: list[dict]) -> None:
    # Write-then-rename, so a crash mid-write cannot leave a truncated lexicon.
    path = lexicon_path()
    tmp = path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def profile() -> dict:
    return json.loads(PROFILE.read_text(encoding="utf-8")) if PROFILE.exists() else {}


def emit(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def current_unit(args_unit: int | None) -> int | None:
    """Prefer an explicit --through-unit, else the furthest position any connection records."""
    if args_unit is not None:
        return args_unit
    units = [c.get("through_unit") for c in profile().get("connections", {}).values()]
    units = [u for u in units if u is not None]
    return max(units) if units else None


def usable(records: list[dict], through: int | None) -> list[dict]:
    """The words chat and quiz may use: unlocked, and not past the course position.

    The course position only gates `exposed`. A word marked shaky or known is evidence
    the learner produced, and that outranks the marker (same rule as set-unit). So does
    `seen` -- a connection (Anki) saying the learner has met the card.
    """
    out = [r for r in records if r.get("confidence") in USABLE]
    if through is not None:
        out = [r for r in out if r.get("confidence") != "exposed" or r.get("seen")
               or (r.get("unit") or 0) <= through]
    return out


def is_structural(rec: dict) -> bool:
    """Particles, articles, copula and honorifics: used freely in chat, never quizzed --
    their glosses are a dump of every English word they ever translate to -- and vocab
    lists them on one line instead of one per word.

    The plugin's is_content() names them; a short unsplittable word the dictionary tags
    as a particle or copula counts too (JMdict gives は no particle POS, so the plugin
    list carries it by hand).
    """
    word = rec.get("word", "")
    L = lang()
    if not L.is_content(word):
        return True
    pos = set(rec.get("pos") or [])
    return bool(pos & {"prt", "cop"}) and len(word) <= 2 and not L.tokens(word)


def glosses(rec: dict) -> list[str]:
    """The record's English glosses as clean strings, whatever shape `gloss` is in."""
    raw = rec.get("gloss")
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    out = []
    for g in raw:
        if isinstance(g, str):
            g = g.strip()
            if re.search(r"[A-Za-z0-9]", g):  # drop empty and punctuation-only junk
                out.append(g)
    return out


def _gloss_key(g: str) -> str:
    """'(the) old', '(an) old' and 'old' are one gloss for display purposes."""
    g = re.sub(r"\([^)]*\)", "", g.lower())
    g = re.sub(r"^to\s+", "", g.strip())
    return re.sub(r"\s+", " ", g).strip() or g


def distinct_glosses(rec: dict) -> list[str]:
    """Glosses deduplicated, with purely parenthetical notes like '(softens the tone)' last."""
    gs = glosses(rec)
    gs = [g for g in gs if not re.fullmatch(r"\(.*\)", g)] + [g for g in gs if re.fullmatch(r"\(.*\)", g)]
    seen, out = set(), []
    for g in gs:
        k = _gloss_key(g)
        if k not in seen:
            seen.add(k)
            out.append(g)
    return out


def gloss_label(rec: dict) -> str:
    """A short English label -- quiz options have to fit on one line."""
    return "/".join(distinct_glosses(rec)[:2])[:60] or rec["word"]


def reading_of(rec: dict) -> str | None:
    """The record's reading field, whatever the language calls it (kana / reading)."""
    return rec.get("kana") or rec.get("reading") or None


def word_label(rec: dict) -> str:
    """The word with its reading, as the plugin shows it: 食べる [たべる]."""
    reading = lang().reading_label(rec)
    return f"{rec['word']} [{reading}]" if reading else rec["word"]


jp_label = word_label  # the pre-registry name


STOPWORDS = frozenset(
    "a an the to of is it its be am are was were will going do does did i i'm im you he she "
    "we they my your and or in on at for with not that this as by".split()
)


def gloss_tokens(rec: dict) -> set[str]:
    """Content words across all glosses, crudely singularised: coats -> coat, Mr. -> mr."""
    out = set()
    for g in glosses(rec):
        for tok in re.findall(r"[a-z0-9']+", g.lower()):
            tok = tok.strip("'")
            if tok in STOPWORDS or (len(tok) < 2 and not tok.isdigit()):
                continue
            if len(tok) > 3 and tok.endswith("s") and not tok.endswith("ss"):
                tok = tok[:-1]
            out.add(tok)
    return out


def key_of(rec: dict, counts: dict[str, int]) -> str:
    """What `mark` needs to find this record again: the word, or word[kana] when the
    surface form alone is shared by several records (分 is both ふん and ぶん)."""
    w = rec["word"]
    reading = reading_of(rec)
    return f"{w}[{reading}]" if counts.get(w, 0) > 1 and reading else w


def word_counts(records: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in records:
        counts[r["word"]] = counts.get(r["word"], 0) + 1
    return counts


def is_due(rec: dict, on: str | None = None) -> bool:
    srs = rec.get("srs")
    return isinstance(srs, dict) and bool(srs.get("due")) and srs["due"] <= (on or today())


def schedule(srs: dict | None, level: str, on: str) -> dict | None:
    """The next srs value after marking a word `level` on day `on`."""
    if level not in ("shaky", "known"):
        return srs
    srs = srs if isinstance(srs, dict) else None
    if level == "shaky":
        box = 1
    elif srs and srs.get("due") and srs["due"] > on:
        return {**srs, "last": on}  # known, but early: no promotion
    else:
        box = min(int((srs or {}).get("box") or 1) + 1, len(INTERVALS))
    due = (date.fromisoformat(on) + timedelta(days=INTERVALS[box - 1])).isoformat()
    return {"box": box, "due": due, "last": on}


def resolve(token: str, records: list[dict], usable_ids: set[int] | None = None) -> list[dict]:
    """Find the records a learner-facing token means.

    Tried in order, first tier with a hit wins: exact word, word[reading], written form
    (kanji / headword), reading (kana / reading), any spelling variant, and finally the
    plugin's normalised form (Bonjour -> bonjour). Within a tier, usable words beat
    unseen ones, since a session can only have surfaced a word the learner has.
    """
    m = re.fullmatch(r"(.+)\[(.+)\]", token)
    norm = lang().normalise
    tiers = [lambda r: r["word"] == token]
    if m:
        tiers.append(lambda r: r["word"] == m[1] and reading_of(r) == m[2])
    tiers += [
        lambda r: token in (r.get("kanji"), r.get("headword")),
        lambda r: token in (r.get("kana"), r.get("reading")),
        lambda r: token in (r.get("variants") or []),
        lambda r: norm(r["word"]) == norm(token),
    ]
    for test in tiers:
        hits = [r for r in records if test(r)]
        if not hits:
            continue
        if len(hits) > 1 and usable_ids is not None:
            preferred = [r for r in hits if id(r) in usable_ids]
            hits = preferred or hits
        return hits
    return []


def is_listed(rec: dict) -> bool:
    """On a test list. `jlpt` is the pre-registry name of `listed`."""
    return bool(rec.get("listed", rec.get("jlpt")))


def compact_line(rec: dict, n: int = 3) -> str:
    label = lang().reading_label(rec)
    reading = f"[{label}]" if label else ""
    return f"{rec['word']}{reading} {'/'.join(distinct_glosses(rec)[:n])}".rstrip()


def cmd_stats(args) -> None:
    records = load()
    by_conf = {lvl: 0 for lvl in LEVELS}
    for r in records:
        by_conf[r.get("confidence", "unseen")] = by_conf.get(r.get("confidence", "unseen"), 0) + 1
    units = sorted({r["unit"] for r in records if r.get("unit")})
    origins: dict[str, int] = {}
    for r in records:
        for s in r.get("sources", []):
            origins[s] = origins.get(s, 0) + 1
    ratings: dict[str, int] = {}
    for r in records:
        label = level_label(r.get("rating"))
        if label:
            ratings[label] = ratings.get(label, 0) + 1
    chat = usable(records, current_unit(None))
    names = names_path()
    emit(
        {
            "language": code(),
            "total": len(records),
            "names_excluded": sum(1 for _ in names.read_text(encoding="utf-8").splitlines()) if names.exists() else 0,
            "by_confidence": by_conf,
            # What chat actually receives -- vocab applies the course position too,
            # so counting every usable word here would overstate it.
            "usable_for_chat": len(chat),
            "structural": sum(1 for r in chat if is_structural(r)),
            "due_for_review": sum(1 for r in chat if is_due(r)),
            "scheduled": sum(1 for r in records if isinstance(r.get("srs"), dict)),
            "by_source": origins,
            "by_rating": {k: ratings.get(k, 0) for k in level_order()},
            "on_test_list": sum(1 for r in records if is_listed(r)),
            "rated_by_inference": sum(1 for r in records if r.get("rating") and not is_listed(r)),
            "units_in_course": len(units),
            "through_unit": current_unit(None),
        }
    )


def cmd_vocab(args) -> None:
    """The chat skill's working vocabulary: every word it is allowed to use."""
    through = current_unit(args.through_unit)
    records = usable(load(), through)
    if args.script:
        records = [r for r in records if r.get("script") == args.script]
    if args.confidence:
        records = [r for r in records if r.get("confidence") == args.confidence]
    records.sort(key=lambda r: (r.get("unit") or 0, r.get("order", 0)))
    if args.limit:
        records = records[: args.limit]

    if args.compact:
        # One line per word -- the form to actually paste into a prompt. Structural
        # words go on one trailing line: their glosses are noise, not meaning.
        structural = [r for r in records if is_structural(r)]
        for r in records:
            if not is_structural(r):
                print(compact_line(r))
        counts = word_counts(records)
        recycle = [key_of(r, counts) for r in records if r.get("confidence") == "shaky" or is_due(r)]
        if recycle:
            print("recycle (shaky or due): " + " ".join(dict.fromkeys(recycle)))
        if structural:
            print("structural (particles/copula): " + " ".join(dict.fromkeys(r["word"] for r in structural)))
        return
    emit(
        {
            "count": len(records),
            "through_unit": through,
            "structural": list(dict.fromkeys(r["word"] for r in records if is_structural(r))),
            "words": records,
        }
    )


def cmd_set_unit(args) -> None:
    """Record course position and promote everything up to it from unseen to exposed."""
    records = load()
    promoted = 0
    demoted = 0
    for r in records:
        unit = r.get("unit")
        if unit is None:
            continue
        if unit <= args.unit and r.get("confidence") == "unseen":
            r["confidence"] = "exposed"
            promoted += 1
        elif unit > args.unit and r.get("confidence") == "exposed":
            # Moving the marker back un-exposes words, but never touches shaky/known:
            # if the learner has demonstrated a word, that evidence outranks the marker.
            r["confidence"] = "unseen"
            demoted += 1
    save(records)

    p = profile()
    # A manual override is recorded against the connection it overrides.
    p.setdefault("connections", {}).setdefault(args.connection, {})["through_unit"] = args.unit
    p["updated"] = date.today().isoformat()
    PROFILE.parent.mkdir(parents=True, exist_ok=True)
    PROFILE.write_text(json.dumps(p, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    emit({"through_unit": args.unit, "promoted": promoted, "demoted": demoted, "usable": sum(1 for r in records if r.get("confidence") in USABLE)})


def cmd_mark(args) -> None:
    """Record what a session observed: mark WORD LEVEL [WORD LEVEL ...].

    WORD may be the record's word, its kanji form, its kana reading, any spelling
    variant, or word[kana] to pick between records sharing a surface form. Words that
    cannot be resolved are reported and skipped; everything else is written in one save.
    """
    if len(args.pairs) % 2:
        sys.exit("mark expects WORD LEVEL pairs")
    updates = dict(zip(args.pairs[::2], (v.lower() for v in args.pairs[1::2])))
    bad = [v for v in updates.values() if v not in LEVELS]
    if bad:
        sys.exit(f"unknown confidence {bad} -- expected one of {LEVELS}")

    records = load()
    counts = word_counts(records)
    usable_ids = {id(r) for r in records if r.get("confidence") in USABLE}
    on = today()
    changed: list[str] = []
    resolved: dict[str, str] = {}
    ambiguous: dict[str, list[str]] = {}
    missing: list[str] = []
    scheduled: dict[str, dict] = {}
    for token, level in updates.items():
        hits = resolve(token, records, usable_ids)
        if not hits:
            missing.append(token)
            continue
        if len(hits) > 1:
            ambiguous[token] = [key_of(r, counts) if counts[r["word"]] > 1 else r["word"] for r in hits][:8]
            continue
        rec = hits[0]
        key = key_of(rec, counts)
        rec["confidence"] = level
        rec["seen_count"] = (rec.get("seen_count") or 0) + 1
        rec["last_seen"] = on
        rec["srs"] = schedule(rec.get("srs"), level, on)
        changed.append(key)
        if key != token:
            resolved[token] = key
        if isinstance(rec["srs"], dict) and level in ("shaky", "known"):
            scheduled[key] = rec["srs"]
    if changed:
        save(records)
    out: dict = {"updated": changed, "not_in_lexicon": missing}
    if resolved:
        out["resolved"] = resolved
    if ambiguous:
        out["ambiguous"] = ambiguous  # retry these as word[kana]
    if scheduled:
        out["srs"] = scheduled
    emit(out)


def cmd_review(args) -> None:
    """Words the Leitner schedule says to revisit: due today, or every scheduled word."""
    records = load()
    counts = word_counts(records)
    on = today()
    rows = [r for r in records if isinstance(r.get("srs"), dict) and r.get("confidence") in USABLE]
    if not args.all:
        rows = [r for r in rows if is_due(r, on)]
    rows.sort(key=lambda r: (r["srs"].get("due") or "", r["srs"].get("box") or 0, r["word"]))
    if args.limit:
        rows = rows[: args.limit]
    if args.compact:
        for r in rows:
            s = r["srs"]
            print(f"{compact_line(r, 2)}  ({r.get('confidence')}, box {s.get('box')}, due {s.get('due')})")
        return
    emit(
        {
            "today": on,
            "count": len(rows),
            "words": [
                {
                    "word": key_of(r, counts),
                    "kana": reading_of(r),  # the reading, whatever the language calls it
                    "gloss": gloss_label(r),
                    "confidence": r.get("confidence"),
                    "box": r["srs"].get("box"),
                    "due": r["srs"].get("due"),
                    "last": r["srs"].get("last"),
                }
                for r in rows
            ],
        }
    )


def cmd_tests(args) -> None:
    """Exam coverage per registry level, easiest first, however many levels there are.

    `on_list` counts only words genuinely in a test list -- that is the number that
    means anything for exam readiness. `inferred` counts words graded at this level by
    decomposition or containment, useful for pitching chat but not exam progress.
    """
    records = load()
    order = level_order()
    report = {}
    for label in order:
        n = languages.rating_of(label, order)
        listed = [r for r in records if r.get("rating") == n and is_listed(r)]
        inferred = [r for r in records if r.get("rating") == n and not is_listed(r)]
        if not listed and not inferred:
            continue
        known = sum(1 for r in listed if r.get("confidence") in USABLE)
        report[label] = {
            "on_list": len(listed),
            "unlocked": known,
            "percent": round(100 * known / len(listed), 1) if listed else 0.0,
            "inferred": len(inferred),
        }
    by_method = {}
    for r in records:
        if r.get("rating_source"):
            by_method[r["rating_source"]] = by_method.get(r["rating_source"], 0) + 1
    spec = languages.spec(code())
    emit({"language": code(), "official": bool((spec.get("tests") or {}).get("official")),
          "levels": report, "graded_by": by_method})


def quiz_priority(rec: dict, on: str) -> tuple:
    """Due first (oldest due), then shaky, then the least-tested exposed, then known."""
    if is_due(rec, on):
        return (0, rec["srs"]["due"])
    conf = rec.get("confidence")
    if conf == "shaky":
        return (1, rec.get("last_seen") or "")
    if conf == "exposed":
        return (2, rec.get("seen_count") or 0, rec.get("last_seen") or "")
    return (3, rec.get("last_seen") or "")


def cmd_quiz(args) -> None:
    """Build multiple-choice items the quiz skill can put straight into a question.

    Distractors come from here rather than from the model: picking them from the same
    test rating is what makes a wrong answer mean "did not know the word" instead of
    "had never seen any of these".
    """
    all_records = load()
    counts = word_counts(all_records)
    on = today()
    records = usable(all_records, current_unit(args.through_unit))
    # Structural words are never asked and never offered: "and/that/door/with" is not
    # an answer anyone can be wrong about in a useful way.
    pool = [r for r in records if not is_structural(r) and distinct_glosses(r)]
    if len(pool) < 4:
        emit({"direction": args.direction, "count": 0, "items": [], "error": f"only {len(pool)} usable words -- not enough for a quiz"})
        return

    candidates = pool
    if args.only == "due":
        candidates = [r for r in pool if is_due(r, on)]
    elif args.only == "shaky":
        candidates = [r for r in pool if r.get("confidence") == "shaky"]
    elif args.only == "new":
        candidates = [r for r in pool if r.get("confidence") == "exposed" and not r.get("seen_count")]
    if not candidates:
        emit({"direction": args.direction, "count": 0, "items": [], "error": f"no {args.only} words to quiz"})
        return

    rng = random.Random(args.seed)
    candidates = list(candidates)
    rng.shuffle(candidates)  # shuffle first so the sort below breaks ties randomly
    candidates.sort(key=lambda r: quiz_priority(r, on))

    from_english = args.direction in ("en2jp", "en2target")
    label = word_label if from_english else gloss_label
    prompt_of = gloss_label if from_english else word_label
    tokens = {id(r): gloss_tokens(r) for r in pool}

    items = []
    for rec in candidates:
        if len(items) >= args.count:
            break
        answer = label(rec)
        seen = {answer.casefold()}
        distractors: list[str] = []
        same_level = [r for r in pool if r is not rec and r.get("rating") == rec.get("rating")]
        # Sample rather than scan: the pool is sorted by priority, so taking the first
        # matches would hand every item in a round the same three distractors.
        fallback = list(pool)
        rng.shuffle(same_level)
        rng.shuffle(fallback)
        for source in (same_level, fallback):
            for other in source:
                if len(distractors) == 3:
                    break
                if other is rec or other["word"] == rec["word"]:
                    continue
                # A distractor sharing a meaning word with the answer is a second right
                # answer: coat/coats, three (三) / three (三つ), eat (食べます) / eat (たべます).
                if tokens[id(other)] & tokens[id(rec)]:
                    continue
                other_label = label(other)
                if other_label.casefold() in seen:
                    continue  # two options reading the same is a free elimination
                seen.add(other_label.casefold())
                distractors.append(other_label)
        if len(distractors) < 2:
            continue  # a two-option question tests nothing
        options = [answer] + distractors
        rng.shuffle(options)
        items.append(
            {
                "word": key_of(rec, counts),  # the key `mark` expects
                "prompt": prompt_of(rec),
                "answer": answer,
                "options": options,
                "confidence": rec.get("confidence"),
                "rating": level_label(rec.get("rating")),
                "due": is_due(rec, on),
            }
        )
    emit({"direction": args.direction, "count": len(items), "items": items})


def cmd_look(args) -> None:
    """Full records. Accepts the same forms as mark; an ambiguous form returns a list."""
    records = load()
    usable_ids = {id(r) for r in records if r.get("confidence") in USABLE}
    out = {}
    for w in args.words:
        hits = [_with_alias(r) for r in resolve(w, records, usable_ids)]
        out[w] = hits[0] if len(hits) == 1 else (hits or None)
    emit(out)


def _with_alias(rec: dict) -> dict:
    """`look` keeps the old `jlpt` key beside `listed` for one release."""
    if "listed" in rec and "jlpt" not in rec:
        return {**rec, "jlpt": rec["listed"]}
    return rec


def script_choices() -> list[str]:
    """The registry's scripts for every language, plus mixed/other/latin."""
    try:
        scripts = {s for spec in languages.registry().values() for s in spec.get("scripts", [])}
    except (OSError, ValueError):
        scripts = set()
    return sorted(scripts | {"mixed", "other", "latin"})


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("stats", help="counts by confidence and course coverage").set_defaults(fn=cmd_stats)
    sub.add_parser("tests", help="coverage against the language's test lists").set_defaults(fn=cmd_tests)

    v = sub.add_parser("vocab", help="words chat is allowed to use")
    v.add_argument("--through-unit", type=int, help="override the recorded course position")
    v.add_argument("--script", choices=script_choices(), help="only words written in this script")
    v.add_argument("--confidence", choices=LEVELS)
    v.add_argument("--limit", type=int)
    v.add_argument("--compact", action="store_true", help="one line per word, prompt-ready")
    v.set_defaults(fn=cmd_vocab)

    s = sub.add_parser("set-unit", help="manually record course position")
    s.add_argument("unit", type=int)
    s.add_argument("--connection", default="Duolingo", help="which connection this position belongs to")
    s.set_defaults(fn=cmd_set_unit)

    m = sub.add_parser("mark", help="record observed confidence: WORD LEVEL [WORD LEVEL ...]")
    m.add_argument("pairs", nargs="+")
    m.set_defaults(fn=cmd_mark)

    q = sub.add_parser("quiz", help="multiple-choice items drawn from the unlocked words")
    q.add_argument("--count", type=int, default=8)
    q.add_argument("--direction", choices=["jp2en", "en2jp", "target2en", "en2target"], default="jp2en",
                   help="jp2en/target2en: word -> English meaning; en2jp/en2target: the reverse. "
                        "jp* names are kept for the skills and mean the active language")
    q.add_argument("--through-unit", type=int)
    q.add_argument("--only", choices=["due", "shaky", "new"], help="restrict the asked words (distractors still come from everything)")
    q.add_argument("--seed", type=int, help="fix the draw, for testing")
    q.set_defaults(fn=cmd_quiz)

    r = sub.add_parser("review", help="words due for review on the Leitner schedule")
    r.add_argument("--all", action="store_true", help="every scheduled word, not just those due")
    r.add_argument("--limit", type=int)
    r.add_argument("--compact", action="store_true", help="one line per word, prompt-ready")
    r.set_defaults(fn=cmd_review)

    lk = sub.add_parser("look", help="show full records for words")
    lk.add_argument("words", nargs="+")
    lk.set_defaults(fn=cmd_look)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
