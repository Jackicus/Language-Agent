#!/usr/bin/env python3
"""One command from nothing to a lexicon /chat can use.

    python setup.py                      full first run (needs username.txt or a username)
    python setup.py <duolingo-username>  write Connections/Duolingo/username.txt, then full run
    python setup.py --language fr        practise French (written to Profile/profile.json first)
    python setup.py --anki deck.apkg     also read an Anki export (remembered, so --sync re-reads it)
                    [--deck NAME]        ...only this deck of it
    python setup.py --check              doctor: what is present / missing / stale; no network
    python setup.py --sync               daily refresh: connections + build + showcase
    python setup.py --refresh            full run, re-fetching the test lists and dictionary
    python setup.py --no-showcase        skip build_showcase.py (combinable)

The language is chosen once: --language, else the one already in Profile/profile.json,
else the active course of the Duolingo account. A Duolingo username is only needed when
Duolingo is a source:  python setup.py --language fr --anki deck.apkg  works without one.

Every successful run ends with one machine-readable line:  SUMMARY {...json...}
"""

import sys

# The real floor: build_lexicon.py uses str.removeprefix and dict | dict (3.9). Kept
# above every other line so an old interpreter gets this sentence, not a traceback.
MIN_PYTHON = (3, 9)
if sys.version_info < MIN_PYTHON:
    sys.exit("Language-Agent needs Python %d.%d or newer; this is %d.%d. Install a newer Python and re-run."
             % (MIN_PYTHON + sys.version_info[:2]))

import argparse
import collections
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

for stream in (sys.stdout, sys.stderr):  # Windows consoles default to cp1252
    if hasattr(stream, "reconfigure"):  # line-buffered so piped stdout and stderr stay in order
        stream.reconfigure(encoding="utf-8", line_buffering=True)

ROOT = Path(__file__).resolve().parent
REGISTRY = ROOT / "languages.json"
DUO = ROOT / "Connections" / "Duolingo"
FETCH = DUO / "data" / "fetch"
USERNAME = DUO / "username.txt"
ANKI = ROOT / "Connections" / "Anki"
ANKI_FETCH = ANKI / "data" / "fetch" / "fetch-anki.py"
SCRIPTS = ROOT / "Profile" / "data" / "scripts"
# LEXICON_DIR overrides Profile/ as a whole (CONTRACTS §1); <code>/ still applies under it.
PROFILE_DIR = Path(os.environ.get("LEXICON_DIR") or ROOT / "Profile")
LEARNER = PROFILE_DIR / "profile.json"
SHOWCASE = ROOT / "showcase.html"
TESTS = ROOT / "Resources" / "Tests"
DICTIONARY = ROOT / "Resources" / "Dictionary"
HOSTS = {"jlpt": "GitHub", "jmdict": "GitHub"}  # for "could not reach X"; anything else says "the network"
STALE_AFTER = 24 * 3600  # Duolingo artefacts older than a day are worth a --sync

# The last line of a traceback when the network, not the code, is at fault.
NETWORK_RE = re.compile(r"^(urllib\.error\.\w+|socket\.\w+|ssl\.\w+|http\.client\.\w+|TimeoutError|"
                        r"Connection\w*Error|BrokenPipeError)\b")


# ---------------------------------------------------------------- language registry

def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except ValueError:
        return {}


def load_registry() -> dict:
    """languages.json without its _doc key, in file order (Japanese first)."""
    reg = {k: v for k, v in read_json(REGISTRY).items() if not k.startswith("_")}
    if not reg:
        sys.exit(f"{REGISTRY.name} is missing or empty -- it lists the languages this project can build.")
    return reg


REG = load_registry()


def code_of(value) -> Optional[str]:
    """A registry code from a code, a name ("Japanese", the pre-registry form) or a duome code."""
    if not value:
        return None
    v = str(value).strip()
    if v in REG:
        return v
    for code, e in REG.items():
        if v.lower() in (e["name"].lower(), str(e.get("duolingo", "")).lower()):
            return code
    return None


def saved_language() -> Optional[str]:
    return code_of(read_json(LEARNER).get("language"))


def write_language(code: str) -> None:
    """Profile/profile.json.language = code, every other key kept."""
    p = read_json(LEARNER)
    if p.get("language") == code:
        return
    p = {"language": code, **{k: v for k, v in p.items() if k != "language"}}
    LEARNER.parent.mkdir(parents=True, exist_ok=True)
    LEARNER.write_text(json.dumps(p, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def supported() -> str:
    return ", ".join(f"{c} ({e['name']})" for c, e in REG.items())


def kept(code: Optional[str]) -> str:
    """The " -- its words stay in Profile/<code>/" suffix, or "" when there is nothing to keep."""
    if not code or not (lexicon_path(code).exists() or legacy_lexicon(code)):
        return ""
    return f" -- your {REG[code]['name']} words stay in {rel(PROFILE_DIR / code)}/ for when you switch back"


def lexicon_path(code: str) -> Path:
    return PROFILE_DIR / code / "lexicon.jsonl"


def legacy_lexicon(code: str) -> Optional[Path]:
    """The pre-registry flat Profile/lexicon.jsonl, which build_lexicon moves into Profile/ja/."""
    flat = PROFILE_DIR / "lexicon.jsonl"
    return flat if code == "ja" and flat.exists() and not lexicon_path(code).exists() else None


# ---------------------------------------------------------------- connections

def username() -> str:
    return USERNAME.read_text(encoding="utf-8").strip() if USERNAME.exists() else ""


def duo_courses() -> dict:
    return read_json(DUO / "profile.json").get("courses") or {}


def course_code(course: dict) -> Optional[str]:
    """The registry code of a Duolingo course, matched on the registry's `duolingo` value
    (duome calls Mandarin "zs", not "zh"), then on the language name."""
    learning = str(course.get("learning_language") or "").lower()
    for code, e in REG.items():
        if learning and learning == str(e.get("duolingo", "")).lower():
            return code
    return code_of(course.get("language"))


def course_for(code: str, courses: dict):
    """(key, course) of the Duolingo course teaching this language, or (None, None)."""
    return next(((k, c) for k, c in courses.items() if course_code(c) == code), (None, None))


def active_course(courses: dict):
    return next(((k, c) for k, c in courses.items() if c.get("active")), (None, None))


def anki_deck(code: Optional[str]) -> Optional[dict]:
    """What fetch-anki.py last read for this language -- {file, deck, fields} from the
    courses["en-<code>"] entry of Connections/Anki/profile.json -- so --sync can re-read it."""
    if not code:
        return None
    courses = read_json(ANKI / "profile.json").get("courses") or {}
    course = next((c for c in courses.values() if c.get("learning_language") == code and c.get("file")), None)
    return {k: course.get(k) for k in ("file", "deck", "fields")} if course else None


def anki_args(deck: dict) -> list:
    args = [deck["file"]] + (["--deck", deck["deck"]] if deck.get("deck") else [])
    for name, value in (deck.get("fields") or {}).items():  # a field mapping chosen once is kept
        if value is not None:
            args += [f"--field-{name}", str(value)]
    return args


# ---------------------------------------------------------------- steps

@dataclass
class Step:
    title: str
    script: Optional[Path]                       # None: the registry names no fetcher
    args: list = field(default_factory=list)
    outputs: list = field(default_factory=list)  # artefacts this step writes
    kind: str = "duolingo"                       # duolingo | anki | resource | build | showcase
    host: str = "duome.eu"
    hint: str = ""
    skip: str = ""                               # non-empty: print this instead of running
    want: int = 0                                # resource: how many outputs make it complete


def tests_files(code: str) -> list:
    e = REG[code]
    src = e["tests"].get("source")
    folder = TESTS / e["name"]
    return sorted(folder.glob(f"{src}-*.csv")) if src and folder.exists() else []


def dictionary_current(path: Path) -> bool:
    """True when the dictionary CSV has the generic schema (CONTRACTS §3), not JMdict's old one."""
    try:
        with path.open(encoding="utf-8-sig") as fh:
            return fh.readline().split(",")[0].strip() == "headword"
    except OSError:
        return False


def resource_state(step: Step) -> str:
    """ok | missing | partial | old schema -- whether a resource step can be skipped."""
    present = [p for p in step.outputs if p.exists()]
    if not present:
        return "missing"
    if len(present) < max(step.want, 1):
        return "partial"
    if step.want == 0 and step.outputs and not dictionary_current(step.outputs[0]):
        return "old schema"
    return "ok"


def plan(code: Optional[str], *, duo: bool, anki: Optional[dict], showcase: bool) -> list:
    """Every step for this language, in order. Same length whatever the language, so the
    [n/N] count printed before the language is known stays true after it is."""
    e = REG.get(code) or {"name": "your language", "tests": {}, "dictionary": {}}
    name, steps = e["name"], []

    if duo:
        key, course = course_for(code, duo_courses()) if code else (None, None)
        missing = f"your Duolingo account has no {name} course" if code and duo_courses() and not course else ""
        frm = (course or {}).get("from_language") or "en"
        learning = (course or {}).get("learning_language") or e.get("duolingo") or code or ""
        steps += [
            Step("Refreshing duome's copy of your profile", FETCH / "refresh-user-profile.py",
                 hint="Check the Duolingo username (it must match your profile exactly) and that the profile is public."),
            Step("Fetching account profile", FETCH / "fetch-user-data.py", outputs=[DUO / "profile.json"]),
            Step("Fetching unit tree", FETCH / "fetch-progress.py", outputs=[DUO / "progress.json"], skip=missing,
                 hint=f"Make sure {name} is your active course in Duolingo, then re-run."),
            Step(f"Fetching {name} course word list", FETCH / "fetch-word-lists.py", [frm, learning], skip=missing,
                 outputs=[DUO / "data" / "languages" / ((course or {}).get("from") or "English")
                          / f"{name.lower()}.csv"] if code else []),
        ]
    if anki:
        moved = "" if Path(anki["file"]).exists() else \
            f"{anki['file']} is not there any more -- point at it again with  python setup.py --anki <file>"
        steps.append(Step("Reading Anki deck", ANKI_FETCH, anki_args(anki), kind="anki", host="", skip=moved,
                          outputs=[ANKI / "data" / "languages" / "English" / f"{name.lower()}.csv"] if code else [],
                          hint="Check the path points at an exported .apkg or a collection.anki2, "
                               "and pass --deck NAME if it holds several decks."))

    tests, dictionary = e["tests"].get("source"), e["dictionary"].get("source")
    levels = e["tests"].get("levels") or []
    steps.append(Step(f"Fetching {tests.upper() if tests else name + ' test'} word lists",
                      TESTS / "data" / "fetch" / f"fetch-{tests}.py" if tests else None,
                      outputs=tests_files(code) or [TESTS / name / f"{tests}-{levels[0].lower()}.csv"] if tests else [],
                      kind="resource", host=HOSTS.get(tests, ""), want=len(levels),
                      skip="" if tests or not code else f"none listed for {name} in languages.json"))
    steps.append(Step(f"Fetching {dictionary or name} dictionary",
                      DICTIONARY / "data" / "fetch" / f"fetch-{dictionary}.py" if dictionary else None,
                      outputs=[DICTIONARY / name / f"{dictionary}.csv"] if dictionary else [],
                      kind="resource", host=HOSTS.get(dictionary, ""),
                      skip="" if dictionary or not code else f"none listed for {name} in languages.json"))
    steps.append(Step(f"Building {name} lexicon", SCRIPTS / "build_lexicon.py",
                      outputs=[lexicon_path(code)] if code else [], kind="build", host=""))
    if showcase:
        steps.append(Step("Building showcase", SCRIPTS / "build_showcase.py", outputs=[SHOWCASE],
                          kind="showcase", host=""))
    return steps


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def age(path: Path) -> str:
    secs = time.time() - path.stat().st_mtime
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if secs >= size:
            return f"{secs / size:.0f}{unit}"
    return f"{secs:.0f}s"


def stats(code: Optional[str]) -> dict:
    """`lexicon.py stats` for this language as a dict, or {} when it has no lexicon yet."""
    if not code or not (lexicon_path(code).exists() or legacy_lexicon(code)):
        return {}
    proc = subprocess.run([sys.executable, str(SCRIPTS / "lexicon.py"), "stats"], capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    try:
        return json.loads(proc.stdout) if proc.returncode == 0 else {}
    except ValueError:
        return {}


def run_step(n: int, total: int, step: Step) -> float:
    """Run one step, streaming its output. Exits the whole run on failure."""
    print(f"\n[{n}/{total}] {step.title}", flush=True)
    if not step.script.exists():
        print(f"\nFAILED at [{n}/{total}] {step.title}: {rel(step.script)} does not exist", file=sys.stderr)
        print("try: update the project (git pull); that script is not in this copy yet.", file=sys.stderr)
        sys.exit(1)
    started = time.monotonic()
    env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
    tail = collections.deque(maxlen=12)
    traceback = []  # held back: shown only if the failure turns out not to be the network
    proc = subprocess.Popen([sys.executable, str(step.script), *step.args], cwd=step.script.parent, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace")
    try:
        for line in proc.stdout:
            line = line.rstrip("\n")
            if traceback or line.startswith("Traceback (most recent call last)"):
                traceback.append(line)
            else:
                print("    " + line, flush=True)
            tail.append(line)
        code = proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        sys.exit(f"\ninterrupted during [{n}/{total}] {step.title}")
    if code == 0:
        took = time.monotonic() - started
        print(f"    done in {took:.1f}s")
        return took

    last = next((l.strip() for l in reversed(tail) if l.strip()), "(no output)")
    print(f"\nFAILED at [{n}/{total}] {step.title} ({rel(step.script)}, exit {code})", file=sys.stderr)
    if traceback and NETWORK_RE.match(last):
        print(f"    could not reach {step.host or 'the network'}: {last}", file=sys.stderr)
        hint = f"Check your internet connection and re-run; {step.host or 'the server'} is sometimes slow or briefly down."
    else:
        for line in (traceback[-12:] if traceback else list(tail)[-6:]):
            print("    " + line, file=sys.stderr)
        hint = step.hint or f"Re-run python setup.py; to debug, run it alone: cd {rel(step.script.parent)} && " \
                            f"python {step.script.name} {' '.join(step.args)}".rstrip()
    print(f"try: {hint}", file=sys.stderr)
    sys.exit(code or 1)


# ---------------------------------------------------------------- --check

def check(code: Optional[str]) -> int:
    """Print what exists and how old it is. No network. 0 when /chat has words to use."""
    name = REG[code]["name"] if code else None
    print(f"language: {name} ({code})" if code else "language: not chosen yet")

    duo = bool(username())
    anki = anki_deck(code)
    steps = plan(code, duo=duo, anki=anki, showcase=True)
    inputs = [o for s in steps if s.kind in ("duolingo", "anki", "resource") for o in s.outputs]
    rows, missing, stale = [], [], []  # rows: (path, step, forced state or "", note)
    if duo or not anki:
        rows.append((USERNAME, None, "", username()))
    for step in steps:
        state = resource_state(step) if step.kind == "resource" and step.script else "ok"
        if state != "ok":
            e = REG[code]
            shown = TESTS / e["name"] / f"{e['tests']['source']}-*.csv" if step.want else step.outputs[0]
            have = sum(p.exists() for p in step.outputs)
            note = {"partial": f"{have} of {step.want} levels", "old schema": "old column names; re-fetched on the next run"}
            rows.append((shown, step, "missing" if state == "missing" else "stale", note.get(state, "")))
            continue
        legacy = legacy_lexicon(code) if step.kind == "build" and code else None
        for out in ([legacy] if legacy else step.outputs):
            rows.append((out, step, "", "old layout; moves to Profile/ja/ on the next build" if legacy else step.skip))

    print(f"{'status':<8} {'age':>5}  artefact")
    for path, step, state, note in rows:
        when = age(path) if path.exists() else "-"
        if not state:
            state = "ok" if path.exists() else "missing"
        if state == "ok" and step:
            if step.kind == "duolingo" and time.time() - path.stat().st_mtime > STALE_AFTER:
                state = "stale"
            deck = Path(anki["file"]) if step.kind == "anki" else None
            if deck and deck.exists() and deck.stat().st_mtime > path.stat().st_mtime:
                state, note = "stale", "the deck file is newer"
            if step.kind in ("build", "showcase"):
                deps = inputs if step.kind == "build" else [o for s in steps if s.kind == "build" for o in s.outputs]
                if any(i.exists() and i.stat().st_mtime > path.stat().st_mtime for i in deps):
                    state = "stale"
        (missing if state == "missing" else stale if state == "stale" else []).append(rel(path))
        print(f"{state:<8} {when:>5}  {rel(path)}" + (f"  ({note})" if note else ""))

    s = stats(code)
    through, usable = s.get("through_unit"), s.get("usable_for_chat", 0)
    ready = bool(s) and usable > 0
    if s:
        print(f"\nlexicon: {s.get('total', 0):,} {name} words"
              + (f" · through unit {through}" if through is not None else "") + f" · {usable:,} usable for chat")
    if ready:
        print("READY for /chat" + ("  (some artefacts are stale: python setup.py --sync)" if stale else ""))
    else:
        if not code:
            why, cmd = "no language chosen", "python setup.py <your-duolingo-username>  or  " \
                                             "python setup.py --language <code> --anki <file>"
        else:
            why = "lexicon still in the old layout" if legacy_lexicon(code) else \
                  f"no {name} lexicon yet" if not s else \
                  "no unit recorded" if through is None and duo else "no usable words"
            cmd = "python setup.py --sync" if duo or anki else "python setup.py <your-duolingo-username>"
        print(f"NOT READY ({why}) -- run  {cmd}  (or type /setup in Claude Code)")
    print("SUMMARY " + json.dumps({"language": code, "ready": ready, "through_unit": through, "usable": usable,
                                   "total": s.get("total", 0), "missing": missing, "stale": stale}))
    return 0 if ready else 1


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("username", nargs="?", help="your Duolingo username (written to username.txt)")
    ap.add_argument("--language", metavar="CODE", help=f"the language to practise: {', '.join(REG)}")
    ap.add_argument("--anki", metavar="FILE", help="an exported .apkg or a collection.anki2 to read")
    ap.add_argument("--deck", metavar="NAME", help="with --anki: read only this deck")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="report what is present/missing/stale; no network")
    mode.add_argument("--sync", action="store_true", help="daily refresh; test lists and dictionary only if missing")
    mode.add_argument("--refresh", action="store_true", help="full run, re-fetching test lists and dictionary")
    ap.add_argument("--no-showcase", action="store_true", help="skip building showcase.html")
    args = ap.parse_args()

    if args.language and args.language not in REG:
        ap.error(f"unknown language {args.language!r}; supported: {supported()}")
    if args.deck and not args.anki:
        ap.error("--deck goes with --anki FILE")

    if args.check:
        if args.username or args.anki:
            ap.error("--check takes no username and no --anki")
        if args.language:
            previous = saved_language()
            write_language(args.language)
            if previous and previous != args.language:
                print(f"switched from {REG[previous]['name']} to {REG[args.language]['name']}{kept(previous)}")
        return check(args.language or saved_language())

    anki_new = None
    if args.anki:
        path = Path(args.anki).expanduser().resolve()
        if not path.is_file():
            ap.error(f"{args.anki} is not a file -- export the deck from Anki (File > Export, .apkg) and pass its path")
        anki_new = {"file": str(path), "deck": args.deck}

    old, old_language = username() or None, saved_language()
    if args.username:
        name = args.username.strip().lstrip("@").rstrip("/").rsplit("/", 1)[-1]
        if not re.fullmatch(r"[\w.-]+", name):
            ap.error(f"{args.username!r} does not look like a Duolingo username")
        USERNAME.parent.mkdir(parents=True, exist_ok=True)
        USERNAME.write_text(name + "\n", encoding="utf-8")
        print(f"username: {name}" + (f" (was {old})" if old and old != name else "") + f" -> {rel(USERNAME)}")
    duo = bool(username())

    # The language: --language, else saved -- unless this is a different Duolingo account,
    # whose active course decides it again -- else inferred after the profile fetch below.
    new_account = bool(args.username and old and old != username())
    code, origin = args.language, "set by --language"
    if not code and not new_account:
        code, origin = saved_language(), ""
    if not code and not duo:
        if anki_new:
            print("Which language is the deck in?  python setup.py --language <code> --anki ...  "
                  f"Supported: {supported()}", file=sys.stderr)
        else:
            print("Nothing to build from yet -- run  python setup.py <your-duolingo-username>  or  "
                  "python setup.py --language <code> --anki <file>", file=sys.stderr)
        return 2

    def anki_for(c):
        return anki_new or anki_deck(c)

    if not duo and not anki_for(code):
        print(f"No source for {REG[code]['name']} yet -- run  python setup.py <your-duolingo-username>  "
              f"or  python setup.py --anki <file>", file=sys.stderr)
        return 2

    def announce(c, why):
        previous = saved_language()
        write_language(c)
        moved = kept(previous) if previous != c else ""
        print(f"Language: {REG[c]['name']}" + (f" ({why})" if why else "") + moved)

    if code:
        announce(code, origin)
    show = not args.no_showcase
    steps = plan(code, duo=duo, anki=anki_for(code), showcase=show)
    total, n = len(steps), 0
    started, skipped, before = time.monotonic(), [], stats(code)
    try:
        if duo:
            for step in steps[:2]:  # refresh + profile: enough to know the active course
                n += 1
                run_step(n, total, step)
            if not code:
                key, course = active_course(duo_courses())
                code = course_code(course or {})
                if not code:
                    what = f"{course.get('language') or key} ({key})" if course else "no active course"
                    print(f"\nYour active Duolingo course is {what}, which Language-Agent does not support yet.\n"
                          f"Supported: {supported()}\n"
                          f"Pick one:  python setup.py --language <code>", file=sys.stderr)
                    return 2
                announce(code, "from your active Duolingo course")
                before = stats(code)
            active_key, active = active_course(duo_courses())
            mine, _ = course_for(code, duo_courses())
            if mine and active_key and mine != active_key:
                print(f"note: your active Duolingo course is {active.get('language')}, not {REG[code]['name']}; "
                      f"unit progress only comes from the active course -- switch it in Duolingo for an "
                      f"up-to-date position.")
            steps = plan(code, duo=duo, anki=anki_for(code), showcase=show)
            total = len(steps)
        for step in steps[n:]:
            n += 1
            if step.skip or not step.script:
                print(f"\n[{n}/{total}] {step.title} -- skipped, {step.skip or 'nothing to fetch'}")
                skipped.append(step.title)
                continue
            if step.kind == "resource" and not args.refresh and resource_state(step) == "ok":
                print(f"\n[{n}/{total}] {step.title} -- skipped, already present (--refresh to re-fetch)")
                skipped.append(step.script.name)
                continue
            run_step(n, total, step)  # fetch-anki records file + deck in its profile.json; --sync reads them back
    except SystemExit:
        if old and args.username and old != username():
            USERNAME.write_text(old + "\n", encoding="utf-8")  # a typo must not replace a working name
            print(f"restored username.txt to {old}", file=sys.stderr)
            if old_language and not args.language and saved_language() != old_language:
                write_language(old_language)  # the language came from that account, so it goes back too
                print(f"restored the language to {REG[old_language]['name']}", file=sys.stderr)
        raise

    after = stats(code)
    if not after:
        print("The build finished but lexicon.py stats could not read the result.", file=sys.stderr)
        return 1
    usable = after.get("usable_for_chat", 0)
    summary = {
        "language": code, "language_name": REG[code]["name"],
        "through_unit": after.get("through_unit"), "usable": usable, "total": after.get("total"),
        "new_usable": usable - before.get("usable_for_chat", 0) if before else 0, "first_run": not before,
        "username": username() or None,
        "connections": (["duolingo"] if duo else []) + (["anki"] if anki_for(code) else []),
        "mode": "sync" if args.sync else "refresh" if args.refresh else "setup",
        "skipped": skipped, "seconds": round(time.monotonic() - started, 1),
    }
    if show:
        summary["showcase"] = str(SHOWCASE)
    change = "first run" if summary["first_run"] else f"{summary['new_usable']:+,} since last run"
    unit = f" (through unit {summary['through_unit']})" if summary["through_unit"] is not None else ""
    print(f"\nready: {usable:,} {REG[code]['name']} words usable for chat{unit}, "
          f"{change} · {summary['seconds']}s")
    print("SUMMARY " + json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:  # `python setup.py --check | head` closed the pipe; nothing left to say
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        sys.exit(1)
