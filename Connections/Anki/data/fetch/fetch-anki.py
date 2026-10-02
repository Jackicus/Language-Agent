#!/usr/bin/env python3
"""Read an Anki deck into the connection word table for the active language.

Anki knows something Duolingo cannot: whether you have actually reviewed a card. A note
whose cards have at least one review gets seen=1, everything else seen=0, and
build_lexicon.py promotes seen=1 words from `unseen` to `exposed` (and nothing more).

Input is either an exported package or a raw collection:

    .apkg / .colpkg   a zip around the SQLite collection (File -> Export ->
                      "Anki Deck Package", with "Include scheduling information" ticked,
                      and "Support older Anki versions" ticked on Anki 2.1.50+)
    collection.anki2  the live collection from your Anki profile folder (close Anki first)

Output:
    data/languages/English/<languagename>.csv   (CONTRACTS section 5 columns; `unit` empty)
    profile.json                                 file, deck, counts, timestamp

The language is the active one in Profile/profile.json (default ja). Fields are numbered
from 1 as Anki's note editor lists them; the default guess is field 1 = word, field
2 = gloss. The guess and three sample rows are printed so a wrong guess is obvious.

Usage:
    python fetch-anki.py deck.apkg --list
    python fetch-anki.py deck.apkg
    python fetch-anki.py deck.apkg --deck "Japanese::Core 2k"
    python fetch-anki.py collection.anki2 --deck Japanese --field-word 2 --field-gloss 4
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import shutil
import sqlite3
import sys
import tempfile
import unicodedata
import zipfile
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE_ROOT = HERE.parent.parent                       # Connections/Anki
PROJECT_ROOT = SOURCE_ROOT.parent.parent
LANGUAGES = SOURCE_ROOT / "data" / "languages"
PROFILE = SOURCE_ROOT / "profile.json"
REGISTRY = PROJECT_ROOT / "languages.json"
LEARNER = PROJECT_ROOT / "Profile" / "profile.json"
PLUGINS = PROJECT_ROOT / "Profile" / "data" / "scripts"

FROM_LANGUAGE = ("en", "English")   # glosses are assumed English, per CONTRACTS section 8
COLUMNS = ["unit", "unit_name", "unit_topic", "position", "word", "reading", "gloss", "script", "repeat_units", "audio", "seen"]
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
SQLITE_MAGIC = b"SQLite format 3\x00"

SOUND_RE = re.compile(r"\[sound:[^\]]*\]")
BREAK_RE = re.compile(r"<\s*(br|/div|/p|/li)\b[^>]*>", re.I)
TAG_RE = re.compile(r"<[^>]+>")
# Anki's furigana syntax: 食[た]べる, 日本語[にほんご]. The base is the run before the bracket.
FURIGANA_RE = re.compile(r" ?([^\s\[\]]+?)\[([^\]]*)\]")


# ---------------------------------------------------------------- language registry

def registry() -> dict:
    try:
        data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise SystemExit(f"{REGISTRY} missing or unreadable -- run  python setup.py  from the project root.")
    return {k: v for k, v in data.items() if not k.startswith("_") and isinstance(v, dict)}


def active_language() -> tuple[str, dict]:
    """(code, registry entry) for Profile/profile.json's language, default ja.

    Accepts a registry key or, for profiles written before the registry existed, a name.
    """
    reg = registry()
    wanted = "ja"
    try:
        wanted = json.loads(LEARNER.read_text(encoding="utf-8")).get("language") or "ja"
    except (OSError, ValueError):
        pass
    if wanted in reg:
        return wanted, reg[wanted]
    for code, entry in reg.items():
        if str(entry.get("name", "")).lower() == str(wanted).lower():
            return code, entry
    raise SystemExit(f"Profile language {wanted!r} is not in languages.json (supported: {', '.join(reg)}).")


def load_plugin(plugin: str | None):
    """The plugin's LANGUAGE object, or None when absent or broken (degrade, never fail)."""
    if not plugin or not (PLUGINS / "languages" / f"{plugin}.py").exists():
        return None
    if str(PLUGINS) not in sys.path:
        sys.path.insert(0, str(PLUGINS))
    try:
        import importlib
        lang = getattr(importlib.import_module(f"languages.{plugin}"), "LANGUAGE", None)
    except Exception as exc:
        print(f"  warning: language plugin {plugin!r} failed to import ({exc}); using generic script detection")
        return None
    return lang if callable(getattr(lang, "script_of", None)) else None


_BLOCKS = (("HIRAGANA", "hiragana"), ("KATAKANA", "katakana"), ("HANGUL", "hangul"), ("LATIN", "latin"))


def generic_script(word: str, scripts) -> str:
    """A registry script if the word uses exactly one, `latin` for Latin, else `mixed`."""
    kinds = set()
    for ch in word:
        if not ch.isalpha():
            continue
        name = unicodedata.name(ch, "")
        if "IDEOGRAPH" in name:
            kinds.add(next((s for s in ("kanji", "hanzi", "hanja") if s in scripts), "ideograph"))
            continue
        for block, label in _BLOCKS:
            if name.startswith(block) or f" {block} " in f" {name} ":
                kinds.add(label)
                break
        else:
            kinds.add("other")
    if len(kinds) == 1:
        kind = kinds.pop()
        if kind == "latin" or kind in scripts:
            return kind
    return "mixed"


def script_classifier(entry: dict):
    scripts = tuple(entry.get("scripts") or ())
    plugin = load_plugin(entry.get("plugin"))
    if plugin is None:
        return (lambda w: generic_script(w, scripts)), "generic"

    allowed = {*scripts, "latin", "mixed"}

    def classify(word: str) -> str:
        # CONTRACTS section 5: a registry script, latin or mixed; anything else -> generic.
        try:
            label = plugin.script_of(word)
        except Exception:
            label = None
        return label if label in allowed else generic_script(word, scripts)
    return classify, f"plugin {entry.get('plugin')}"


# ---------------------------------------------------------------- opening the collection

def open_collection(path: Path, tmp: Path) -> sqlite3.Connection:
    """Copy the SQLite collection out of `path` into `tmp` and open it read-only."""
    if not path.exists():
        raise SystemExit(f"{path} not found.")
    with path.open("rb") as fh:
        head = fh.read(16)

    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            # anki21 (2.1.x) beats anki2 (legacy). A package that has only anki21b
            # carries a placeholder anki2 saying "please update Anki", so never fall
            # back to that one.
            if "collection.anki21" in names:
                member = "collection.anki21"
            elif "collection.anki21b" in names:
                raise SystemExit(
                    f"{path.name} uses Anki's new compressed format (collection.anki21b, zstd), which "
                    "Python's standard library cannot read.\n"
                    "Re-export it: File -> Export -> Anki Deck Package, tick \"Include scheduling "
                    "information\" AND \"Support older Anki versions (slower/larger files)\"."
                )
            elif "collection.anki2" in names:
                member = "collection.anki2"
            else:
                raise SystemExit(f"{path.name} is a zip but holds no Anki collection (found: {', '.join(sorted(names)) or 'nothing'}).")
            db = tmp / "collection.sqlite"
            with zf.open(member) as src, db.open("wb") as dst:
                shutil.copyfileobj(src, dst)
    elif head.startswith(SQLITE_MAGIC):
        # A live collection may be mid-write; copy it (and its WAL) so we never lock Anki out.
        db = tmp / "collection.sqlite"
        shutil.copyfile(path, db)
        wal = path.with_name(path.name + "-wal")
        if wal.exists():
            shutil.copyfile(wal, tmp / "collection.sqlite-wal")
    elif head.startswith(ZSTD_MAGIC):
        raise SystemExit(f"{path.name} is zstd-compressed (Anki's new format). Re-export with \"Support older Anki versions\" ticked.")
    else:
        raise SystemExit(f"{path.name} is neither an .apkg/.colpkg zip nor a SQLite collection.")

    with db.open("rb") as fh:
        compressed = fh.read(4) == ZSTD_MAGIC
    if compressed:
        raise SystemExit(f"The collection inside {path.name} is zstd-compressed. Re-export with \"Support older Anki versions\" ticked.")

    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    # Anki declares some columns COLLATE unicase; without it sqlite refuses those indexes.
    conn.create_collation("unicase", lambda a, b: (a.casefold() > b.casefold()) - (a.casefold() < b.casefold()))
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    except sqlite3.DatabaseError as exc:
        raise SystemExit(f"Could not read {path.name} as an Anki collection ({exc}).")
    if not {"notes", "cards", "col"} <= tables:
        raise SystemExit(f"{path.name} is SQLite but not an Anki collection (no notes/cards/col tables).")
    return conn


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def deck_names(conn: sqlite3.Connection) -> dict[int, str]:
    """deck id -> "Parent::Child". Schema 18 has a decks table; older ones keep JSON in col."""
    if table_exists(conn, "decks") and conn.execute("SELECT count(*) FROM decks").fetchone()[0]:
        return {did: name.replace("\x1f", "::") for did, name in conn.execute("SELECT id, name FROM decks")}
    raw = conn.execute("SELECT decks FROM col").fetchone()[0] or "{}"
    return {int(did): d.get("name", str(did)) for did, d in json.loads(raw).items()}


def field_names(conn: sqlite3.Connection) -> dict[int, list[str]]:
    """note type id -> field names in order. Same two-schema split as decks."""
    if table_exists(conn, "fields") and conn.execute("SELECT count(*) FROM fields").fetchone()[0]:
        out: dict[int, list[str]] = {}
        for ntid, _ord, name in conn.execute("SELECT ntid, ord, name FROM fields ORDER BY ntid, ord"):
            out.setdefault(ntid, []).append(name)
        return out
    raw = conn.execute("SELECT models FROM col").fetchone()[0] or "{}"
    return {int(mid): [f["name"] for f in sorted(m.get("flds", []), key=lambda f: f.get("ord", 0))]
            for mid, m in json.loads(raw).items()}


def note_type_names(conn: sqlite3.Connection) -> dict[int, str]:
    if table_exists(conn, "notetypes") and conn.execute("SELECT count(*) FROM notetypes").fetchone()[0]:
        return dict(conn.execute("SELECT id, name FROM notetypes"))
    raw = conn.execute("SELECT models FROM col").fetchone()[0] or "{}"
    return {int(mid): m.get("name", str(mid)) for mid, m in json.loads(raw).items()}


# ---------------------------------------------------------------- reading notes

def clean(raw: str) -> str:
    """Field HTML -> plain text: drop [sound:], turn line breaks into newlines, strip tags."""
    text = SOUND_RE.sub("", raw)
    text = BREAK_RE.sub("\n", text)
    text = TAG_RE.sub("", text)
    text = html.unescape(text).replace("\xa0", " ")
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def split_furigana(text: str) -> tuple[str, str]:
    """食[た]べる -> (食べる, たべる). Text without brackets comes back unchanged with no reading."""
    if not FURIGANA_RE.search(text):
        return text, ""
    word = FURIGANA_RE.sub(lambda m: m.group(1), text).strip()
    reading = FURIGANA_RE.sub(lambda m: m.group(2), text).strip()
    return word, reading


def senses(text: str) -> str:
    """Gloss text -> pipe-separated senses (split on newlines, semicolons and commas)."""
    parts = re.split(r"[\n;,]", text)
    seen: dict[str, None] = {}
    for p in parts:
        p = p.strip()
        if p:
            seen.setdefault(p, None)
    return "|".join(seen)


def deck_matches(name: str, wanted: str) -> bool:
    """Exact deck or any of its subdecks, case-insensitively."""
    name, wanted = name.casefold(), wanted.casefold()
    return name == wanted or name.startswith(wanted + "::")


def collect(conn: sqlite3.Connection, deck: str | None):
    """Every note in scope: (note id, note type id, fields, reviewed?, deck name)."""
    decks = deck_names(conn)
    if deck is not None:
        ids = {did for did, name in decks.items() if deck_matches(name, deck)}
        if not ids:
            listing = "\n  ".join(sorted(decks.values()))
            raise SystemExit(f"No deck named {deck!r}. Decks in this file:\n  {listing}")
    else:
        ids = None

    # A card in a filtered deck remembers its home deck in odid; that is the one that counts.
    by_note: dict[int, dict] = {}
    for nid, did, reps in conn.execute("SELECT nid, CASE WHEN odid != 0 THEN odid ELSE did END, reps FROM cards"):
        if ids is not None and did not in ids:
            continue
        entry = by_note.setdefault(nid, {"reviewed": False, "deck": decks.get(did, str(did))})
        entry["reviewed"] = entry["reviewed"] or (reps or 0) > 0

    notes = []
    for nid, mid, flds in conn.execute("SELECT id, mid, flds FROM notes ORDER BY id"):
        if nid in by_note:
            notes.append((nid, mid, flds.split("\x1f"), by_note[nid]["reviewed"], by_note[nid]["deck"]))
    return notes


def list_decks(conn: sqlite3.Connection, path: Path) -> None:
    decks = deck_names(conn)
    counts: dict[int, list[int]] = {}
    notes_in: dict[int, set] = {}
    for nid, did, reps in conn.execute("SELECT nid, CASE WHEN odid != 0 THEN odid ELSE did END, reps FROM cards"):
        c = counts.setdefault(did, [0, 0])
        c[0] += 1
        c[1] += 1 if (reps or 0) > 0 else 0
        notes_in.setdefault(did, set()).add(nid)
    print(f"{path.name}: {len(decks)} decks")
    print(f"  {'notes':>6} {'cards':>6} {'reviewed':>8}  deck")
    for did, name in sorted(decks.items(), key=lambda kv: kv[1].casefold()):
        cards, reviewed = counts.get(did, [0, 0])
        print(f"  {len(notes_in.get(did, ())):>6} {cards:>6} {reviewed:>8}  {name}")
    print("Pass one with --deck NAME (subdecks are included).")


# ---------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Read an Anki .apkg or collection.anki2 into the word table for the active language.",
        epilog="Fields are numbered from 1 in the order Anki's note editor shows them.",
    )
    ap.add_argument("file", type=Path, help=".apkg / .colpkg export, or collection.anki2")
    ap.add_argument("--list", action="store_true", help="list the decks in the file and exit")
    ap.add_argument("--deck", help="only this deck and its subdecks (default: every deck)")
    ap.add_argument("--field-word", type=int, default=1, metavar="N", help="field holding the word (default 1)")
    ap.add_argument("--field-gloss", type=int, default=2, metavar="N", help="field holding the English meaning (default 2)")
    ap.add_argument("--field-reading", type=int, metavar="N", help="field holding the reading, if the deck has one")
    args = ap.parse_args()
    for flag in ("field_word", "field_gloss", "field_reading"):
        value = getattr(args, flag)
        if value is not None and value < 1:
            ap.error(f"--{flag.replace('_', '-')} counts from 1")

    path = args.file.expanduser().resolve()
    with tempfile.TemporaryDirectory() as tmpdir:
        conn = open_collection(path, Path(tmpdir))
        try:
            if args.list:
                list_decks(conn, path)
                return
            notes = collect(conn, args.deck)
            fields = field_names(conn)
            types = note_type_names(conn)
        finally:
            conn.close()

    if not notes:
        raise SystemExit("No notes in scope." + ("" if args.deck else " Try --list."))

    code, entry = active_language()
    script_of, classifier = script_classifier(entry)
    wi, gi = args.field_word - 1, args.field_gloss - 1
    ri = args.field_reading - 1 if args.field_reading else None

    # Show the guess per note type: a deck can mix layouts, and a wrong guess should be obvious.
    print(f"{path.name}" + (f" -- deck {args.deck!r}" if args.deck else " -- all decks") + f" -> {entry['name']} ({code})")
    for mid in sorted({n[1] for n in notes}):
        names = fields.get(mid) or []
        def label(i):
            if i is None:
                return "-"
            return f"{i + 1} \"{names[i]}\"" if i < len(names) else f"{i + 1} (missing: this type has {len(names)} fields)"
        count = sum(1 for n in notes if n[1] == mid)
        print(f"  note type {types.get(mid, mid)!r} ({count} notes), fields: {', '.join(f'{i + 1}={n}' for i, n in enumerate(names))}")
        print(f"    word <- field {label(wi)}   gloss <- field {label(gi)}" + (f"   reading <- field {label(ri)}" if ri is not None else ""))

    rows: dict[str, dict] = {}
    skipped = 0
    for nid, mid, flds, reviewed, deck in notes:
        raw_word = clean(flds[wi]) if wi < len(flds) else ""
        word, reading = split_furigana(raw_word.split("\n")[0] if raw_word else "")
        if ri is not None and ri < len(flds):
            reading = clean(flds[ri]).split("\n")[0] or reading
        gloss = senses(clean(flds[gi])) if gi < len(flds) else ""
        if not word:
            skipped += 1
            continue
        if word in rows:
            # Same word on two notes: seen if either was reviewed, senses merged.
            row = rows[word]
            row["seen"] = max(row["seen"], 1 if reviewed else 0)
            extra = [s for s in gloss.split("|") if s and s not in row["gloss"].split("|")]
            row["gloss"] = "|".join(filter(None, [row["gloss"], *extra]))
            row["reading"] = row["reading"] or reading
            continue
        rows[word] = {
            "unit": "", "unit_name": "", "unit_topic": "",
            "position": len(rows) + 1,
            "word": word,
            "reading": reading,
            "gloss": gloss,
            "script": script_of(word),
            "repeat_units": "",
            "audio": "",
            "seen": 1 if reviewed else 0,
        }

    table = list(rows.values())
    print("  sample:")
    for r in table[:3]:
        print(f"    {r['word']!r:<20} reading={r['reading']!r:<16} gloss={r['gloss']!r:<40} seen={r['seen']}")

    out = LANGUAGES / FROM_LANGUAGE[1] / f"{entry['name'].lower()}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(table)

    seen = sum(r["seen"] for r in table)
    notes_seen = sum(1 for n in notes if n[3])
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    key = f"{FROM_LANGUAGE[0]}-{code}"

    # Same registry shape as Duolingo's profile.json (CONTRACTS section 5): one entry per
    # course, the one just read active. Anki has no units, so through_unit stays null.
    try:
        profile = json.loads(PROFILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        profile = {}
    courses = profile.get("courses", {})
    for course in courses.values():
        course["active"] = False
    courses[key] = {
        "from_language": FROM_LANGUAGE[0],
        "learning_language": code,
        "from": FROM_LANGUAGE[1],
        "language": entry["name"],
        "active": True,
        "through_unit": None,
        "file": str(path),
        "deck": args.deck,
        "notes": len(notes),
        "notes_seen": notes_seen,
        "words": len(table),
        "words_seen": seen,
        "fields": {"word": args.field_word, "gloss": args.field_gloss, "reading": args.field_reading},
        "wordlist": str(out.relative_to(SOURCE_ROOT)),
        "fetched": now,
    }
    profile = {
        "source": "anki",
        "file": str(path),
        "deck": args.deck,
        "language": code,
        "notes": len(notes),
        "notes_seen": notes_seen,
        "words": len(table),
        "words_seen": seen,
        "fetched": now,
        "courses": courses,
    }
    PROFILE.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    scripts: dict[str, int] = {}
    for r in table:
        scripts[r["script"]] = scripts.get(r["script"], 0) + 1
    print(f"  {len(notes)} notes, {notes_seen} reviewed -> {len(table)} words, {seen} seen" + (f", {skipped} with an empty word field skipped" if skipped else ""))
    print(f"  by script ({classifier}): " + ", ".join(f"{k}={v}" for k, v in sorted(scripts.items(), key=lambda kv: -kv[1])))
    print(f"wrote {out.relative_to(PROJECT_ROOT)} + {PROFILE.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
